"""FastAPI app: the /ws endpoint and static client serving."""

import asyncio
import html
import logging
import os
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from server.auth import SESSION_COOKIE, router as auth_router, verify_google_credential
from server import anticheat, endless, live, overview, players, push, social
from server.db import DEFAULT_PATH, Database
from server.protocol import CLIENT_MESSAGE, ErrorMessage
from server.questions.validate import load_bank, servable
from server.rooms import SPICY_CATEGORY, Hub, Session, save_endless_round, save_game
from server.shop import router as shop_router
from server.social_api import router as social_router

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)

CLIENT_DIST = Path(__file__).resolve().parent.parent / "client" / "dist"
ALLOWED_ORIGINS = [o for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o]
ALLOW_UNVERIFIED = os.environ.get("ALLOW_UNVERIFIED_QUESTIONS") == "1"
# Files from client/public that must sit at the site's root, never under /assets: the service
# worker (its scope is the folder it's served from) and what installing to a Home Screen reads.
ROOT_FILES = {
    "sw.js": "text/javascript",
    "manifest.webmanifest": "application/manifest+json",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
    "apple-touch-icon.png": "image/png",
}

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Runs while the server is up: the nightly live game's scheduler (M6), unless LIVE_MODE=0.
    Tests use TestClient without a `with`, so this never starts in them."""
    task = asyncio.create_task(live.run(hub)) if live.enabled() else None
    yield
    if task is not None:
        task.cancel()


app = FastAPI(title="Almanac", lifespan=lifespan)
# On app.state so tests can swap them; the hub and the socket endpoint read them from there.
app.state.db = Database(os.environ.get("DATABASE_PATH", DEFAULT_PATH))
app.state.verify_google = verify_google_credential
hub = Hub(
    servable(load_bank(), allow_unverified=ALLOW_UNVERIFIED),
    on_game_over=lambda room: save_game(app.state.db, room),
    db=lambda: app.state.db,
    on_round_over=lambda room: save_endless_round(app.state.db, room),
)
app.include_router(auth_router)  # before the client catch-all, which would swallow /api
app.include_router(shop_router)
app.include_router(social_router)
app.include_router(push.router)
app.include_router(anticheat.router)  # M6: the accuracy flags' review queue
app.include_router(players.router)  # the players page: every account's standing, for the team
app.include_router(overview.router_for(hub))  # the overview page: structure, plans, services, status
app.include_router(live.router_for(hub))  # M6: the nightly live game
app.include_router(endless.router_for(hub))  # M6: the endless table's page
app.state.pusher = push.start(lambda: app.state.db)  # None unless the VAPID keys are set


@app.get("/api/categories")
def categories() -> list[dict]:
    """The question categories a host can choose from, with how many servable questions each
    has. Spicy is left out: drinks mode draws it."""
    counts = Counter(q.category for q in hub.questions if q.category != SPICY_CATEGORY)
    return [{"id": category, "count": count} for category, count in sorted(counts.items())]


@app.websocket("/ws")
async def websocket_endpoint(socket: WebSocket) -> None:
    if ALLOWED_ORIGINS and socket.headers.get("origin") not in ALLOWED_ORIGINS:
        await socket.close(code=1008)
        return
    await socket.accept()
    user = socket.app.state.db.user_for_session(socket.cookies.get(SESSION_COOKIE))
    session = Session(socket, user)
    try:
        while True:
            frame = await socket.receive()
            if frame["type"] == "websocket.disconnect":
                break
            raw = frame.get("text") or frame.get("bytes") or ""
            try:
                message = CLIENT_MESSAGE.validate_json(raw)
            except ValidationError:
                await session.send(
                    ErrorMessage(code="bad_message", message="That message wasn't valid.")
                )
                continue
            await hub.handle(session, message)
    finally:
        await hub.disconnect(session)


class HashedAssets(StaticFiles):
    """Vite names every file under /assets by its content hash, so a given URL never changes:
    browsers may keep these forever."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


if (CLIENT_DIST / "index.html").is_file():
    app.mount("/assets", HashedAssets(directory=CLIENT_DIST / "assets"), name="assets")

    def invite_page(request: Request, public_id: str, code: str) -> str | None:
        """The page for a group's invite link, with the title and tags a messaging app reads to
        draw the link's preview: "Join Fintech Club on Almanac", the group's bio, its picture.
        None when the link isn't a live invite; then the plain page is served. Everything a
        player wrote is escaped, and a reported name, bio or picture is left out, as it is for
        anyone else who isn't the owner."""
        try:
            group = social.group_preview(request.app.state.db, public_id, code)
        except social.SocialError:
            return None
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        origin = f"{scheme if scheme in ('http', 'https') else 'https'}://{request.headers.get('host', request.url.netloc)}"
        count = group["member_count"]
        title = f"Join {group['name']} on Almanac"
        about = group["bio"] or f"{count} {'member' if count == 1 else 'members'} so far. Trade what you think you know."
        tags = {
            "og:type": "website",
            "og:site_name": "Almanac",
            "og:title": title,
            "og:description": about,
            "og:image": origin + (group["icon"]["image"] or "/icon-512.png"),
            "twitter:card": "summary",
        }
        head = f"<title>{html.escape(title)}</title>" + "".join(
            f'<meta property="{name}" content="{html.escape(value, quote=True)}" />' for name, value in tags.items()
        )
        page = (CLIENT_DIST / "index.html").read_text(encoding="utf-8")
        return page.replace("<title>Almanac</title>", head, 1)

    @app.get("/{path:path}")
    def client_route(path: str, request: Request) -> Response:
        # The page must be rechecked on every load (a cheap 304 when nothing changed). Without
        # this, browsers kept a stale page after a deploy and ran the old client against the new
        # catalog: new hair styles had no art and drew bald (Nov 4, 2026).
        if path in ROOT_FILES:
            return FileResponse(
                CLIENT_DIST / path, media_type=ROOT_FILES[path], headers={"Cache-Control": "no-cache"}
            )
        code = request.query_params.get("invite")
        if code and path.startswith("g/"):
            page = invite_page(request, path[2:].strip("/"), code)
            if page is not None:
                return HTMLResponse(page, headers={"Cache-Control": "no-cache"})
        return FileResponse(CLIENT_DIST / "index.html", headers={"Cache-Control": "no-cache"})
