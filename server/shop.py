"""The marketplace and locker room: catalog, purchases, and the equipped avatar."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server import achievements
from server.auth import current_user
from server.cosmetics import (
    BUNDLE_DISCOUNT,
    BUNDLES_BY_ID,
    ITEMS,
    catalog_payload,
    road_payload,
    round_price,
    unlocked_for,
    validate_avatar,
)

router = APIRouter(prefix="/api")


class Purchase(BaseModel):
    item_id: str


class BundlePurchase(BaseModel):
    bundle_id: str


class AvatarChange(BaseModel):
    avatar: dict[str, str | None]


def _signed_in(request: Request) -> dict:
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in first.")
    return user


@router.get("/catalog")
def catalog() -> dict:
    return catalog_payload()


def _unlocked(user: dict) -> list[str]:
    return sorted(unlocked_for(user["level"], user["prestige"]))


@router.get("/locker")
def locker(request: Request) -> dict:
    user = _signed_in(request)
    return {
        "user": user,
        "owned": request.app.state.db.inventory(user["id"]),
        "unlocked": _unlocked(user),
    }


@router.get("/academia")
@router.get("/road")  # the page's first name; kept so a client cached before the rename still works
def road(request: Request) -> dict:
    """Academia (the trophy road): what this player has unlocked and what comes next."""
    user = _signed_in(request)
    return {"user": user, **road_payload(user["level"], user["prestige"])}


@router.post("/shop/buy")
def buy(body: Purchase, request: Request) -> dict:
    user = _signed_in(request)
    item = ITEMS.get(body.item_id)
    if item is None:
        raise HTTPException(404, "No such item.")
    if item.free:
        raise HTTPException(400, f"{item.name} is free; just equip it in the locker room.")
    if item.earned:
        raise HTTPException(400, f"{item.name} is earned, not bought.")
    db = request.app.state.db
    try:
        db.buy(user["id"], item.id, item.price)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return _after_purchase(db, user)


def _after_purchase(db, user: dict) -> dict:
    """A purchase can earn spending and collecting achievements; they pay out at once and come
    back with the locker so the marketplace can say so."""
    earned = achievements.award(db, user["id"])
    return {
        "user": db.profile(user["id"])["user"],
        "owned": db.inventory(user["id"]),
        "unlocked": _unlocked(user),
        "achievements": earned,
    }


@router.post("/shop/buy-bundle")
def buy_bundle(body: BundlePurchase, request: Request) -> dict:
    user = _signed_in(request)
    bundle = BUNDLES_BY_ID.get(body.bundle_id)
    if bundle is None:
        raise HTTPException(404, "No such bundle.")
    db = request.app.state.db
    owned = set(db.inventory(user["id"]))
    missing = [item_id for item_id in bundle.items if item_id not in owned]
    if not missing:
        raise HTTPException(400, "You already own everything in this bundle.")
    shares = {item_id: round_price(ITEMS[item_id].price * BUNDLE_DISCOUNT) for item_id in missing}
    try:
        db.buy_many(user["id"], shares, bundle.price_for(owned))
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return _after_purchase(db, user)


@router.get("/achievements")
def achievement_list(request: Request) -> dict:
    """Every achievement with its tiers, rewards and this player's progress. Opening it also
    credits any lifetime tier already reached (accounts older than achievements, say)."""
    user = _signed_in(request)
    db = request.app.state.db
    earned = achievements.award(db, user["id"])
    return {"user": db.profile(user["id"])["user"], "new": earned, **achievements.list_view(db, user["id"])}


@router.put("/avatar")
def set_avatar(body: AvatarChange, request: Request) -> dict:
    user = _signed_in(request)
    db = request.app.state.db
    wearable = set(db.inventory(user["id"])) | set(_unlocked(user))
    try:
        clean = validate_avatar(body.avatar, wearable)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return {"user": db.set_avatar(user["id"], clean)}
