"""Google sign-in and session cookies.

The database and the credential verifier live on app.state, so tests can swap them.
"""

import os

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from server import achievements, social
from server.moderation import clean_bio

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
ALLOW_DEV_LOGIN = os.environ.get("ALLOW_DEV_LOGIN") == "1"
SESSION_COOKIE = "almanac_session"
COOKIE_MAX_AGE = 90 * 24 * 3600


class GoogleCredential(BaseModel):
    credential: str = Field(min_length=1)


class DevLogin(BaseModel):
    name: str = Field(min_length=1, max_length=40)


def verify_google_credential(credential: str) -> dict:
    """Checks a Google ID token and returns the identity it carries. Raises ValueError."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    if not GOOGLE_CLIENT_ID:
        raise ValueError("GOOGLE_CLIENT_ID is not set")
    info = id_token.verify_oauth2_token(credential, google_requests.Request(), GOOGLE_CLIENT_ID)
    if not info.get("email_verified"):
        raise ValueError("email not verified")
    return {
        "sub": info["sub"],
        "email": info["email"],
        "name": info.get("name") or info["email"].split("@")[0],
        "picture": info.get("picture", ""),
    }


def _start_session(request: Request, response: Response, token: str) -> None:
    # Behind Fly's proxy the app sees plain HTTP; the forwarded header says what the user used.
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def current_user(request: Request) -> dict | None:
    return request.app.state.db.user_for_session(request.cookies.get(SESSION_COOKIE))


router = APIRouter(prefix="/api")


@router.get("/config")
def config() -> dict:
    return {"google_client_id": GOOGLE_CLIENT_ID, "dev_login": ALLOW_DEV_LOGIN}


@router.post("/auth/google")
def google_sign_in(body: GoogleCredential, request: Request, response: Response) -> dict:
    try:
        identity = request.app.state.verify_google(body.credential)
    except ValueError as error:
        raise HTTPException(401, "Google sign-in failed.") from error
    user, token = request.app.state.db.sign_in_google(**identity)
    _start_session(request, response, token)
    return {"user": user}


@router.post("/auth/dev")
def dev_sign_in(body: DevLogin, request: Request, response: Response) -> dict:
    if not ALLOW_DEV_LOGIN:
        raise HTTPException(404, "Not found.")
    user, token = request.app.state.db.sign_in_google(
        sub=f"dev:{body.name}", email=f"{body.name}@dev.local", name=body.name
    )
    _start_session(request, response, token)
    return {"user": user}


@router.post("/auth/logout")
def sign_out(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        request.app.state.db.sign_out(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"user": None}


@router.get("/me")
def me(request: Request) -> dict:
    from server import players  # imported here: server/players.py imports this module

    user = current_user(request)
    if user is None:
        return {"user": None}
    # `admin` opens the review pages (ADMIN_EMAILS); `team` opens the players page, which admins
    # and the teammates they've added may see. Everyone else gets False for both.
    admin = social.is_admin(user)
    return {"user": {**user, "admin": admin, "team": admin or players.on_team(request.app.state.db, user)}}


@router.get("/profile")
def profile(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in to see your profile.")
    db = request.app.state.db
    body = db.profile(user["id"])
    body["badges"] = achievements.badges(db, user["id"])  # hardest first, for the showcase
    return body


@router.get("/games")
def game_history(request: Request, before: int | None = Query(None, ge=1)) -> dict:
    """Every game the signed-in player has finished, newest first, a page at a time."""
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in to see your games.")
    return request.app.state.db.history(user["id"], before)


@router.get("/games/{game_id}")
def game_log(game_id: int, request: Request) -> dict:
    """One past game from the signed-in player's side; only someone who played in it gets it."""
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in to see your games.")
    db = request.app.state.db
    detail = db.game_detail(user["id"], game_id)
    if detail is None:
        raise HTTPException(404, "That game isn't in your log.")
    # Each signed-in player's relation to you drives the "Add friend" button. Account ids are
    # for this lookup only and never leave the server.
    accounts = [p["user_id"] for p in detail["players"] if p["user_id"] is not None]
    relation = social.relations(db, user["id"], accounts)
    for player in detail["players"]:
        player["relation"] = relation.get(player.pop("user_id"))
    return detail


class BioChange(BaseModel):
    bio: str


@router.put("/profile/bio")
def set_bio(body: BioChange, request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in first.")
    try:
        bio = clean_bio(body.bio)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return {"user": request.app.state.db.set_bio(user["id"], bio)}
