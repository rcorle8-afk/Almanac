"""The social layer's HTTP API (M5): handles and friend codes, friends, blocks, public
profiles, the notification bell, groups, and reports with their review page.

Everything here needs a sign-in, except what an invite link shows before joining: a group's
preview and its picture. Accounts and groups are named by their public ids. The rules live in
server/social.py; a SocialError becomes an HTTP error with the player-readable reason.
"""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from server import images, social
from server.auth import current_user

router = APIRouter(prefix="/api")


def _me(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in first.")
    return user


def _run(action: Callable[[], Any]) -> Any:
    try:
        return action()
    except social.SocialError as error:
        raise HTTPException(error.status, str(error)) from error
    except ValueError as error:  # moderation's checks on names and handles
        raise HTTPException(400, str(error)) from error


# Identity.


class HandleChange(BaseModel):
    handle: str = Field(max_length=40)


@router.put("/profile/handle")
def set_handle(body: HandleChange, request: Request) -> dict:
    user = _me(request)
    return {"handle": _run(lambda: social.set_handle(request.app.state.db, user["id"], body.handle))}


@router.post("/profile/friend-code")
def new_friend_code(request: Request) -> dict:
    user = _me(request)
    return {"friend_code": social.new_code(request.app.state.db, user["id"])}


@router.get("/u/{public_id}")
def public_profile(public_id: str, request: Request) -> dict:
    user = _me(request)
    return _run(lambda: social.public_profile(request.app.state.db, user["id"], public_id))


# Friends.


@router.get("/social")
def overview(request: Request) -> dict:
    user = _me(request)
    return social.overview(request.app.state.db, user["id"])


@router.get("/social/search")
def search(request: Request, q: str = Query("", max_length=40)) -> dict:
    user = _me(request)
    return {"results": social.search(request.app.state.db, user["id"], q)}


class FriendRequest(BaseModel):
    """Exactly one of the two: a link id (from a profile, the game log or the room) or a
    friend code someone shared."""

    public_id: str | None = Field(default=None, max_length=40)
    friend_code: str | None = Field(default=None, max_length=20)


@router.post("/friends")
def send_request(body: FriendRequest, request: Request) -> dict:
    user = _me(request)
    db = request.app.state.db

    def act() -> dict:
        if body.friend_code:
            other = social.user_id_for_code(db, body.friend_code)
        elif body.public_id:
            other = social.user_id_for(db, body.public_id)
        else:
            raise social.SocialError("Say who to add.")
        return {"relation": social.send_request(db, user["id"], other)}

    return _run(act)


def _with_other(request: Request, public_id: str, action: Callable[[Any, int, int], str]) -> dict:
    user = _me(request)
    db = request.app.state.db
    return _run(lambda: {"relation": action(db, user["id"], social.user_id_for(db, public_id))})


@router.post("/friends/{public_id}/accept")
def accept(public_id: str, request: Request) -> dict:
    return _with_other(request, public_id, social.accept_request)


@router.post("/friends/{public_id}/decline")
def decline(public_id: str, request: Request) -> dict:
    return _with_other(request, public_id, social.decline_request)


@router.delete("/friends/{public_id}")
def remove(public_id: str, request: Request) -> dict:
    return _with_other(request, public_id, social.remove)


@router.post("/blocks/{public_id}")
def block(public_id: str, request: Request) -> dict:
    return _with_other(request, public_id, social.block)


@router.delete("/blocks/{public_id}")
def unblock(public_id: str, request: Request) -> dict:
    return _with_other(request, public_id, social.unblock)


# The bell.


@router.get("/notifications")
def notifications(request: Request) -> dict:
    user = _me(request)
    return social.notifications(request.app.state.db, user["id"])


@router.post("/notifications/read")
def mark_read(request: Request) -> dict:
    user = _me(request)
    social.mark_read(request.app.state.db, user["id"])
    return {"unread": 0}


# Groups.


class GroupName(BaseModel):
    name: str = Field(max_length=80)


class GroupNew(BaseModel):
    """A group being started: its name, and its bio and icon if they were chosen up front."""

    name: str = Field(max_length=80)
    bio: str = Field(default="", max_length=400)
    glyph: str | None = Field(default=None, max_length=20)
    color: str | None = Field(default=None, max_length=20)


class GroupChange(BaseModel):
    """What the owner is changing; anything left out stays as it is."""

    name: str | None = Field(default=None, max_length=80)
    bio: str | None = Field(default=None, max_length=400)
    glyph: str | None = Field(default=None, max_length=20)
    color: str | None = Field(default=None, max_length=20)


class Invitee(BaseModel):
    public_id: str = Field(max_length=40)


class LinkInvite(BaseModel):
    """The code from an invite link, when that's how the player got here."""

    invite: str | None = Field(default=None, max_length=40)


@router.post("/groups")
def create_group(body: GroupNew, request: Request) -> dict:
    """Starts a group, for social.GROUP_COST coins."""
    user = _me(request)
    db = request.app.state.db
    return _run(lambda: social.create_group(db, user["id"], body.name, body.bio, body.glyph, body.color))


@router.get("/groups/mine")
def my_groups(request: Request) -> dict:
    user = _me(request)
    return {"groups": social.my_groups(request.app.state.db, user["id"])}


@router.get("/groups/{public_id}")
def group(public_id: str, request: Request, invite: str | None = Query(None, max_length=40)) -> dict:
    user = _me(request)
    return _run(lambda: social.group_detail(request.app.state.db, user["id"], public_id, invite))


@router.get("/groups/{public_id}/preview")
def group_preview(public_id: str, request: Request, invite: str = Query("", max_length=40)) -> dict:
    """What an invite link shows before joining. The one group page that needs no sign-in: the
    code in the link is what lets the group be seen."""
    user = current_user(request)
    db = request.app.state.db
    return _run(lambda: social.group_preview(db, public_id, invite, user["id"] if user else None))


@router.patch("/groups/{public_id}")
def change_group(public_id: str, body: GroupChange, request: Request) -> dict:
    """The owner's edits: the name, the bio, and the icon's drawing and colour."""
    user = _me(request)
    db = request.app.state.db

    def act() -> dict:
        if body.name is not None:
            social.rename(db, user["id"], public_id, body.name)
        if body.bio is not None:
            social.set_bio(db, user["id"], public_id, body.bio)
        if body.glyph is not None or body.color is not None:
            social.set_icon(db, user["id"], public_id, body.glyph, body.color)
        return social.group_detail(db, user["id"], public_id)

    return _run(act)


@router.post("/groups/{public_id}/invite-link")
def reset_invite_link(public_id: str, request: Request) -> dict:
    user = _me(request)
    return {"invite_code": _run(lambda: social.reset_invite_link(request.app.state.db, user["id"], public_id))}


@router.get("/groups/{public_id}/image")
def group_image(public_id: str, request: Request) -> Response:
    """The group's uploaded picture. Open to anyone who has the address, unless it's reported;
    then only its owner and the admin reviewing it."""
    user = current_user(request)
    db = request.app.state.db
    viewer = user["id"] if user else None
    picture = _run(lambda: social.group_image(db, public_id, viewer, reviewing=social.is_admin(user)))
    # The address changes with every upload (?v=), so a copy can be kept; private, because what
    # a reported picture's owner is served must not be handed to anyone else.
    return Response(picture, media_type=images.ICON_TYPE, headers={"Cache-Control": "private, max-age=604800"})


@router.put("/groups/{public_id}/image")
async def set_group_image(public_id: str, request: Request) -> dict:
    """The owner uploads a picture as the request's body. It's read only up to the size limit."""
    user = _me(request)
    upload = bytearray()
    async for chunk in request.stream():
        upload.extend(chunk)
        if len(upload) > images.UPLOAD_LIMIT:
            raise HTTPException(413, f"That picture is too big. Keep it under {images.UPLOAD_LIMIT // (1024 * 1024)} MB.")
    db = request.app.state.db
    # Redrawing the picture is real work; off the event loop, so no game waits on it.
    icon = await run_in_threadpool(_run, lambda: social.set_image(db, user["id"], public_id, bytes(upload)))
    return {"icon": icon}


@router.delete("/groups/{public_id}/image")
def remove_group_image(public_id: str, request: Request) -> dict:
    user = _me(request)
    return {"icon": _run(lambda: social.remove_image(request.app.state.db, user["id"], public_id))}


@router.delete("/groups/{public_id}")
def disband_group(public_id: str, request: Request) -> dict:
    user = _me(request)
    _run(lambda: social.disband(request.app.state.db, user["id"], public_id))
    return {"ok": True}


@router.post("/groups/{public_id}/invites")
def invite(public_id: str, body: Invitee, request: Request) -> dict:
    user = _me(request)
    db = request.app.state.db
    return _run(lambda: {"result": social.invite(db, user["id"], public_id, social.user_id_for(db, body.public_id))})


@router.post("/groups/{public_id}/join")
def join_group(public_id: str, request: Request, body: LinkInvite | None = None) -> dict:
    user = _me(request)
    code = body.invite if body else None
    return _run(lambda: social.join(request.app.state.db, user["id"], public_id, code=code))


@router.post("/groups/{public_id}/decline")
def decline_group(public_id: str, request: Request) -> dict:
    user = _me(request)
    _run(lambda: social.decline_invite(request.app.state.db, user["id"], public_id))
    return {"ok": True}


@router.post("/groups/{public_id}/leave")
def leave_group(public_id: str, request: Request) -> dict:
    user = _me(request)
    _run(lambda: social.leave(request.app.state.db, user["id"], public_id))
    return {"ok": True}


@router.delete("/groups/{public_id}/members/{member}")
def remove_member(public_id: str, member: str, request: Request) -> dict:
    user = _me(request)
    db = request.app.state.db
    _run(lambda: social.remove_member(db, user["id"], public_id, social.user_id_for(db, member)))
    return {"ok": True}


# The global leaderboard.


@router.get("/leaderboard")
def leaderboard(request: Request) -> dict:
    """Every group by combined prestige and every player by their own: the top of each, and
    where the caller stands."""
    user = _me(request)
    return social.leaderboard(request.app.state.db, user["id"])


# Reports and review.


class ReportBody(BaseModel):
    kind: str = Field(max_length=20)  # bio, group_name, group_bio or group_image
    public_id: str = Field(max_length=40)  # the account for a player's bio, otherwise the group


@router.post("/reports")
def report(body: ReportBody, request: Request) -> dict:
    user = _me(request)
    _run(lambda: social.report(request.app.state.db, user["id"], body.kind, body.public_id))
    return {"ok": True}


def _admin(request: Request) -> dict:
    user = _me(request)
    if not social.is_admin(user):
        raise HTTPException(403, "This page is for the admin.")
    return user


@router.get("/admin/reports")
def review_queue(request: Request) -> dict:
    _admin(request)
    return {"reports": social.open_reports(request.app.state.db)}


class Resolution(BaseModel):
    action: str = Field(max_length=10)  # restore or clear


@router.post("/admin/reports/{report_id}")
def resolve(report_id: int, body: Resolution, request: Request) -> dict:
    _admin(request)
    _run(lambda: social.resolve(request.app.state.db, report_id, body.action))
    return {"ok": True}
