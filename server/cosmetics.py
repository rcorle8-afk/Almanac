"""The cosmetics catalog: avatar parts, their coolness index, rarity, price, and bundles.

Prices are never set by hand. Every item gets four standardized scores. Three describe the
look (coverage, attention, novelty) and make the index; the fourth, motion, says how much
the item moves and multiplies the price. Rarity follows the price, so the tiers never
overlap and items that change the avatar about as much cost about the same. The client
draws each item by id (client/src/avatar/parts.tsx).
"""

from dataclasses import dataclass

# Slot id -> label, in locker order. Optional slots may be empty.
SLOTS = {
    "skin": "Skin",
    "hair": "Hair",
    "hair_color": "Hair color",
    "eyes": "Eyes",
    "mouth": "Expression",
    "top": "Outfit",
    "head": "Headwear",
    "eyewear": "Eyewear",
    "ears": "Earrings",
    "effect": "Effects",
    "banner": "Banners",
}
OPTIONAL_SLOTS = frozenset({"head", "eyewear", "ears", "effect", "banner"})

WEIGHTS = {"coverage": 0.40, "attention": 0.35, "novelty": 0.25}
MOTION_BONUS = 0.5  # price multiplier is 1 + MOTION_BONUS * motion
PRICE_SCALE = 20  # coins at index 1 with no motion
PRICE_STEP = 5
# Rarity by price floor, checked from the top. Static items land where the index bands put them.
RARITY_FLOORS = (("mythical", 1500), ("legendary", 360), ("epic", 210), ("rare", 100), ("common", 0))
RARITY_ORDER = {rarity: rank for rank, (rarity, _) in enumerate(reversed(RARITY_FLOORS))}
RARITY_COLORS = {
    "common": "#3d8bff",
    "rare": "#ff8c1a",
    "epic": "#a855f7",
    "legendary": "#f5c242",
    "mythical": "#8b5cf6",
}
WELCOME_COINS = 750  # a new account's starting balance (350 until Nov 4, 2026); existing accounts keep theirs
BUNDLE_DISCOUNT = 0.8  # bundles cost this share of their unowned items' prices


def round_price(amount: float) -> int:
    return int(round(amount / PRICE_STEP)) * PRICE_STEP


@dataclass(frozen=True)
class Item:
    id: str
    slot: str
    name: str
    coverage: int = 1  # how much of the avatar it changes
    attention: int = 1  # how much it draws the eye: size, color, contrast
    novelty: int = 1  # how unusual it is next to the plain look
    motion: int = 0  # how much it moves; animated items only
    free: bool = False
    color: str | None = None  # skin, hair, and eye colors carry the fill the renderer uses
    # Earned items (banners, mostly) are never for sale: they unlock on the trophy road at a
    # level or a prestige count, or are reserved for tournament and live-game winners.
    unlock: tuple[str, int] | None = None  # ("level", 7) or ("prestige", 500)
    # "tournament" or "live": reserved, no way to earn it yet. "achievement": granted by an
    # achievement tier (server/achievements.py) straight into the inventory.
    source: str | None = None
    tier: str | None = None  # the rarity of an earned item, since it has no price

    @property
    def earned(self) -> bool:
        return self.unlock is not None or self.source is not None

    @property
    def purchasable(self) -> bool:
        return not self.free and not self.earned

    @property
    def index(self) -> float:
        return round(sum(weight * getattr(self, score) for score, weight in WEIGHTS.items()), 2)

    @property
    def price(self) -> int:
        if self.free or self.earned:
            return 0
        return round_price(PRICE_SCALE * self.index**2 * (1 + MOTION_BONUS * self.motion))

    @property
    def rarity(self) -> str:
        if self.tier is not None:
            return self.tier
        return next(rarity for rarity, floor in RARITY_FLOORS if self.price >= floor)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "slot": self.slot,
            "name": self.name,
            "free": self.free,
            "color": self.color,
            "index": self.index,
            "motion": self.motion,
            "rarity": self.rarity,
            "price": self.price,
            "earned": self.earned,
            "unlock": {"kind": self.unlock[0], "at": self.unlock[1]} if self.unlock else None,
            "source": self.source,
            "scores": {score: getattr(self, score) for score in WEIGHTS},
        }


def _free(id_: str, slot: str, name: str, color: str | None = None) -> Item:
    return Item(id_, slot, name, free=True, color=color)


def _item(
    id_: str, slot: str, name: str, coverage: int, attention: int, novelty: int, motion: int = 0, color=None
) -> Item:
    return Item(id_, slot, name, coverage, attention, novelty, motion, color=color)


CATALOG: list[Item] = [
    # Skin: all free
    _free("skin_1", "skin", "Porcelain", "#f8dcc4"),
    _free("skin_2", "skin", "Fair", "#f1c9a5"),
    _free("skin_3", "skin", "Tan", "#d9a375"),
    _free("skin_4", "skin", "Olive", "#b8824f"),
    _free("skin_5", "skin", "Brown", "#8d5a34"),
    _free("skin_6", "skin", "Deep", "#5c3a21"),
    # Hair styles. Everyday cuts are free (Ryan, Nov 4, 2026); only the showpieces cost coins.
    _free("hair_short", "hair", "Short"),
    _free("hair_buzz", "hair", "Buzz cut"),
    _free("hair_side_part", "hair", "Side part"),
    _free("hair_messy", "hair", "Messy"),
    _free("hair_curly", "hair", "Curly"),
    _free("hair_coils", "hair", "Coils"),
    _free("hair_wavy", "hair", "Wavy"),
    _free("hair_long", "hair", "Long"),
    _free("hair_bob", "hair", "Bob"),
    _free("hair_ponytail", "hair", "Ponytail"),
    _free("hair_bun", "hair", "Top knot"),
    _free("hair_none", "hair", "Bald"),
    _item("hair_spiky", "hair", "Spiky", 2, 3, 3),
    _item("hair_pompadour", "hair", "Pompadour", 2, 4, 4),
    _item("hair_mullet", "hair", "Mullet", 3, 3, 4),
    _item("hair_afro", "hair", "Afro", 3, 3, 3),
    _item("hair_braids", "hair", "Box braids", 3, 3, 3),
    _item("hair_dreads", "hair", "Dreads", 3, 3, 3),
    _item("hair_mohawk", "hair", "Mohawk", 3, 4, 4),
    # Hair colors
    _free("hair_black", "hair_color", "Black", "#1f1a17"),
    _free("hair_brown", "hair_color", "Brown", "#5b3a1e"),
    _free("hair_blonde", "hair_color", "Blonde", "#e2b65a"),
    _free("hair_red", "hair_color", "Red", "#b4442a"),
    _item("hair_silver", "hair_color", "Silver", 2, 2, 3, color="#c9ced6"),
    _item("hair_blue", "hair_color", "Electric blue", 2, 3, 3, color="#3d8bff"),
    _item("hair_pink", "hair_color", "Hot pink", 2, 3, 3, color="#ff5fa8"),
    _item("hair_green", "hair_color", "Slime green", 2, 3, 3, color="#38d16a"),
    _item("hair_rainbow", "hair_color", "Rainbow", 2, 5, 5, color="rainbow"),
    # Eyes: all free
    _free("eyes_brown", "eyes", "Brown", "#5a3a1a"),
    _free("eyes_blue", "eyes", "Blue", "#3a7bd5"),
    _free("eyes_green", "eyes", "Green", "#3f9a4f"),
    _free("eyes_hazel", "eyes", "Hazel", "#8a6a2f"),
    _free("eyes_gray", "eyes", "Gray", "#6f7a88"),
    # Expressions
    _free("mouth_smile", "mouth", "Smile"),
    _free("mouth_grin", "mouth", "Grin"),
    _free("mouth_flat", "mouth", "Poker face"),
    _item("mouth_smirk", "mouth", "Smirk", 1, 2, 1),
    _item("mouth_whoa", "mouth", "Whoa", 1, 2, 2),
    _item("mouth_tongue", "mouth", "Tongue out", 1, 3, 3),
    _item("mouth_gold", "mouth", "Gold tooth", 1, 3, 4),
    _item("mouth_mustache", "mouth", "Mustache", 2, 3, 3),
    _item("mouth_beard", "mouth", "Beard", 3, 3, 2),
    # Outfits
    _free("top_tee_blue", "top", "Blue tee", "#2f6fd6"),
    _free("top_tee_gray", "top", "Gray tee", "#6b7280"),
    _free("top_tee_white", "top", "White tee", "#e5e7eb"),
    _item("top_polo", "top", "Polo", 4, 1, 1, color="#0f766e"),
    _item("top_hoodie", "top", "Hoodie", 4, 2, 1, color="#374151"),
    _item("top_jersey", "top", "Jersey", 4, 3, 2, color="#dc2626"),
    _item("top_flannel", "top", "Flannel", 4, 3, 2, color="#b91c1c"),
    _item("top_labcoat", "top", "Lab coat", 4, 2, 3, color="#f3f4f6"),
    _item("top_shirt_tie", "top", "Shirt and tie", 4, 3, 3, color="#f9fafb"),
    _item("top_hivis", "top", "Hi-vis vest", 4, 4, 2, color="#f59e0b"),
    _item("top_hawaiian", "top", "Hawaiian shirt", 4, 4, 3, color="#f472b6"),
    _item("top_suit", "top", "Suit", 4, 4, 3, color="#1f2937"),
    _item("top_tuxedo", "top", "Tuxedo", 4, 4, 4, color="#111827"),
    _item("top_armour", "top", "Plate armour", 5, 4, 5, color="#9ca3af"),
    _item("top_royal_robe", "top", "Royal robe", 5, 5, 4, color="#7f1d1d"),
    _item("top_galaxy_armour", "top", "Galaxy armour", 5, 5, 5, 5, color="#312e81"),
    # Headwear
    _item("head_headband", "head", "Headband", 2, 2, 1, color="#ef4444"),
    _item("head_bandana", "head", "Bandana", 2, 2, 2, color="#1d4ed8"),
    _item("head_cap", "head", "Cap", 3, 2, 1, color="#1d4ed8"),
    _item("head_beanie", "head", "Beanie", 3, 2, 1, color="#16a34a"),
    _item("head_beret", "head", "Beret", 3, 3, 2, color="#111827"),
    _item("head_cowboy", "head", "Cowboy hat", 3, 3, 3, color="#92400e"),
    _item("head_chef", "head", "Chef hat", 3, 3, 3, color="#f9fafb"),
    _item("head_hardhat", "head", "Construction helmet", 3, 4, 3, color="#facc15"),
    _item("head_knight", "head", "Knight helmet", 3, 4, 4, color="#9ca3af"),
    _item("head_tophat", "head", "Top hat", 3, 4, 4, color="#111827"),
    _item("head_halo", "head", "Halo", 2, 5, 5, color="#fde047"),
    _item("head_viking", "head", "Viking helmet", 3, 4, 5, color="#9ca3af"),
    _item("head_pirate", "head", "Pirate hat", 3, 4, 5, color="#111827"),
    _item("head_wizard", "head", "Wizard hat", 4, 4, 4, color="#4c1d95"),
    _item("head_astronaut", "head", "Space helmet", 5, 4, 5, color="#e5e7eb"),
    _item("head_crown", "head", "Crown", 4, 5, 5, color="#f5c242"),
    # Eyewear
    _item("eye_reading", "eyewear", "Reading glasses", 1, 2, 2),
    _item("eye_round", "eyewear", "Round glasses", 2, 2, 2),
    _item("eye_patch", "eyewear", "Eye patch", 1, 3, 4),
    _item("eye_monocle", "eyewear", "Monocle", 1, 3, 5),
    _item("eye_goggles", "eyewear", "Ski goggles", 2, 3, 3),
    _item("eye_aviators", "eyewear", "Aviators", 2, 4, 2),
    _item("eye_sunglasses", "eyewear", "Sunglasses", 2, 4, 3),
    _item("eye_3d", "eyewear", "3D glasses", 2, 4, 4),
    _item("eye_visor", "eyewear", "Cyber visor", 2, 5, 4),
    # Earrings
    _item("ears_studs", "ears", "Studs", 1, 1, 1),
    _item("ears_pearls", "ears", "Pearls", 1, 1, 2),
    _item("ears_hoops", "ears", "Hoops", 1, 2, 2),
    _item("ears_diamonds", "ears", "Diamonds", 1, 4, 4),
    # Effects: always animated, so every one has motion
    _item("effect_sparkles", "effect", "Sparkles", 3, 3, 3, 1),
    _item("effect_lightning", "effect", "Lightning", 3, 4, 3, 1),
    _item("effect_cash", "effect", "Money rain", 4, 5, 5, 2),
    _item("effect_fire", "effect", "On fire", 5, 5, 5, 2),
    _item("effect_void", "effect", "Void aura", 5, 5, 5, 5),
]

# Banners sit behind a player's name on leaderboards and chips: dark fills, hairlines, ruled and
# dotted patterns, one small glyph, slow motion on the rarer ones. The names are the game's own
# jokes about estimating. A few are for sale and priced like everything else; the ones that
# matter are earned, so they say something about the player that coins can't. The colors are
# the client's fallback swatch; the art is CSS in styles.module.css, one class per id.
BANNERS: list[Item] = [
    _item("banner_ballpark", "banner", "Ballpark", 2, 2, 1, color="#1a212c"),
    _item("banner_envelope", "banner", "Back of the Envelope", 3, 3, 2, color="#121a28"),
    _item("banner_thumb", "banner", "Rule of Thumb", 3, 4, 3, color="#141821"),
    _item("banner_guess", "banner", "Educated Guess", 3, 4, 4, motion=1, color="#0f1623"),
    _item("banner_magnitude", "banner", "Order of Magnitude", 3, 5, 4, motion=2, color="#0d1118"),
    _item("banner_fermi", "banner", "Fermi", 5, 5, 5, motion=5, color="#0b1322"),
    # The trophy road. Levels are for showing up; prestige is for being right.
    Item("banner_luck", "banner", "Beginner's Luck", unlock=("level", 2), tier="common", color="#161b23"),
    Item("banner_suspect", "banner", "Usual Suspect", unlock=("level", 4), tier="rare", color="#141c2b"),
    Item("banner_knowitall", "banner", "Know-It-All", unlock=("level", 7), tier="epic", color="#121826"),
    Item("banner_almanac", "banner", "Walking Almanac", unlock=("level", 10), tier="legendary", motion=1, color="#0f1a2e"),
    Item("banner_oracle", "banner", "Oracle", unlock=("level", 15), tier="mythical", motion=5, color="#0b0d12"),
    Item("banner_close", "banner", "Close Enough", unlock=("prestige", 150), tier="rare", color="#15202e"),
    Item("banner_spoton", "banner", "Spot On", unlock=("prestige", 500), tier="epic", color="#0f1727"),
    Item("banner_reckoning", "banner", "Dead Reckoning", unlock=("prestige", 1200), tier="legendary", motion=2, color="#12151c"),
    Item("banner_crystal", "banner", "Crystal Ball", unlock=("prestige", 2500), tier="mythical", motion=5, color="#07080c"),
    # Reserved for M6: nobody can earn these until tournaments and live games exist.
    Item("banner_podium", "banner", "Podium", source="tournament", tier="mythical", motion=3, color="#0c0a06"),
    Item("banner_primetime", "banner", "Prime Time", source="live", tier="mythical", motion=3, color="#060b14"),
    # Achievement rewards (server/achievements.py): granted into the inventory when the tier
    # that carries them is earned; never sold.
    Item("banner_onaroll", "banner", "On a Roll", source="achievement", tier="epic", color="#1c4532"),
    Item("banner_trophycase", "banner", "Trophy Case", source="achievement", tier="epic", color="#1c3a85"),
    Item("banner_deeppockets", "banner", "Deep Pockets", source="achievement", tier="epic", color="#2b1f4d"),
    Item("banner_fullhouse", "banner", "Full House", source="achievement", tier="epic", color="#13203b"),
    Item("banner_deadcenter", "banner", "Dead Center", source="achievement", tier="legendary", motion=1, color="#0b0c0f"),
    Item("banner_comeback", "banner", "Comeback Kid", source="achievement", tier="mythical", motion=3, color="#1c4532"),
]
# Headwear only an achievement can give (Regular gold, Champion platinum).
ACHIEVEMENT_HATS: list[Item] = [
    Item("head_mortarboard", "head", "Mortarboard", source="achievement", tier="epic"),
    Item("head_laurels", "head", "Laurel wreath", source="achievement", tier="legendary"),
]
CATALOG.extend(ACHIEVEMENT_HATS)
CATALOG.extend(BANNERS)

ITEMS: dict[str, Item] = {item.id: item for item in CATALOG}

# The trophy road, in the order a player walks it: every earned item with a threshold.
TROPHY_ROAD: list[Item] = sorted(
    (item for item in CATALOG if item.unlock is not None),
    key=lambda item: (item.unlock[0] != "level", item.unlock[1]),
)
RESERVED: list[Item] = [item for item in CATALOG if item.source in ("tournament", "live")]


def unlocked_for(level: int, prestige: int) -> set[str]:
    """The earned items a player at this level and prestige may wear."""
    standing = {"level": level, "prestige": prestige}
    return {item.id for item in TROPHY_ROAD if standing[item.unlock[0]] >= item.unlock[1]}


def road_payload(level: int, prestige: int) -> dict:
    unlocked = unlocked_for(level, prestige)
    return {
        "levels": [
            {"at": item.unlock[1], "item": item.to_dict(), "unlocked": item.id in unlocked}
            for item in TROPHY_ROAD
            if item.unlock[0] == "level"
        ],
        "prestige": [
            {"at": item.unlock[1], "item": item.to_dict(), "unlocked": item.id in unlocked}
            for item in TROPHY_ROAD
            if item.unlock[0] == "prestige"
        ],
        "reserved": [item.to_dict() for item in RESERVED],
    }


@dataclass(frozen=True)
class Bundle:
    id: str
    name: str
    blurb: str
    items: tuple[str, ...]

    @property
    def full_price(self) -> int:
        return sum(ITEMS[item_id].price for item_id in self.items)

    def price_for(self, owned: set[str]) -> int:
        """The discounted price of whatever the player doesn't own yet."""
        missing = [ITEMS[item_id].price for item_id in self.items if item_id not in owned]
        return round_price(BUNDLE_DISCOUNT * sum(missing))

    @property
    def rarity(self) -> str:
        return max((ITEMS[item_id].rarity for item_id in self.items), key=RARITY_ORDER.__getitem__)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "blurb": self.blurb,
            "items": list(self.items),
            "full_price": self.full_price,
            "price": self.price_for(set()),
            "rarity": self.rarity,
        }


BUNDLES: list[Bundle] = [
    Bundle("bundle_knight", "Knight", "Plate armour and the helmet to match.", ("top_armour", "head_knight")),
    Bundle(
        "bundle_business",
        "Business",
        "A suit, smart glasses, and money falling from the sky.",
        ("top_suit", "eye_round", "effect_cash"),
    ),
    Bundle("bundle_builder", "Site crew", "Hard hat and hi-vis. Safety first.", ("head_hardhat", "top_hivis")),
    Bundle(
        "bundle_rockstar",
        "Rock star",
        "Mohawk, shades, and lightning on demand.",
        ("hair_mohawk", "eye_sunglasses", "effect_lightning"),
    ),
    Bundle(
        "bundle_royalty",
        "Royalty",
        "Crown, robe, and a sparkle wherever you go.",
        ("head_crown", "top_royal_robe", "effect_sparkles"),
    ),
    Bundle("bundle_pirate", "Pirate", "Hat, patch, and a beard that's seen things.", ("head_pirate", "eye_patch", "mouth_beard")),
]
BUNDLES_BY_ID: dict[str, Bundle] = {bundle.id: bundle for bundle in BUNDLES}

DEFAULT_AVATAR = {
    "skin": "skin_3",
    "hair": "hair_short",
    "hair_color": "hair_black",
    "eyes": "eyes_brown",
    "mouth": "mouth_smile",
    "top": "top_tee_blue",
    "head": None,
    "eyewear": None,
    "ears": None,
    "effect": None,
    "banner": None,
}


def stored_avatar(config: dict | None) -> dict:
    """An avatar as saved, made wearable again: a slot whose item has since left the catalog
    (renamed, retired) falls back to the slot's default instead of failing every later save."""
    clean = dict(DEFAULT_AVATAR)
    for slot in SLOTS:
        item_id = (config or {}).get(slot)
        item = ITEMS.get(item_id) if item_id else None
        if item is not None and item.slot == slot:
            clean[slot] = item_id
    return clean


def validate_avatar(config: dict, owned: set[str]) -> dict:
    """Returns a clean avatar: every slot filled, every item real, free, or in `owned`, which
    is everything the player bought plus everything the trophy road has unlocked for them."""
    clean = {}
    for slot in SLOTS:
        item_id = config.get(slot)
        if item_id is None:
            if slot in OPTIONAL_SLOTS:
                clean[slot] = None
                continue
            item_id = DEFAULT_AVATAR[slot]
        item = ITEMS.get(item_id)
        if item is None or item.slot != slot:
            raise ValueError(f"{item_id} isn't a {SLOTS[slot].lower()} option")
        if not item.free and item_id not in owned:
            if item.earned:
                raise ValueError(f"You haven't earned {item.name} yet")
            raise ValueError(f"You don't own {item.name}")
        clean[slot] = item_id
    return clean


def catalog_payload() -> dict:
    return {
        "slots": [
            {"id": slot, "label": label, "optional": slot in OPTIONAL_SLOTS} for slot, label in SLOTS.items()
        ],
        "items": [item.to_dict() for item in CATALOG],
        "bundles": [bundle.to_dict() for bundle in BUNDLES],
        "bundle_discount": BUNDLE_DISCOUNT,
        "rarity_colors": RARITY_COLORS,
        "welcome_coins": WELCOME_COINS,
    }
