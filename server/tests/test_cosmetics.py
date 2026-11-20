from pathlib import Path

import pytest

from server.cosmetics import (
    BUNDLE_DISCOUNT,
    BUNDLES,
    BUNDLES_BY_ID,
    CATALOG,
    DEFAULT_AVATAR,
    ITEMS,
    OPTIONAL_SLOTS,
    RARITY_COLORS,
    RARITY_FLOORS,
    SLOTS,
    WEIGHTS,
    WELCOME_COINS,
    catalog_payload,
    round_price,
    stored_avatar,
    validate_avatar,
)

PAID = [item for item in CATALOG if item.purchasable]
EARNED = [item for item in CATALOG if item.earned]
STATIC = [item for item in PAID if item.motion == 0]
ART_DIR = Path(__file__).resolve().parents[2] / "client" / "src" / "avatar"
INDEX_BANDS = (("common", 2.25), ("rare", 3.25), ("epic", 4.25), ("legendary", 99))


class TestCatalogShape:
    def test_ids_are_unique(self):
        assert len(ITEMS) == len(CATALOG)

    def test_every_item_is_in_a_known_slot_with_sane_scores(self):
        for item in CATALOG:
            assert item.slot in SLOTS
            for score in WEIGHTS:
                assert 1 <= getattr(item, score) <= 5, item.id
            assert 0 <= item.motion <= 5, item.id

    def test_every_required_slot_has_a_free_option(self):
        for slot in SLOTS:
            if slot not in OPTIONAL_SLOTS:
                assert any(item.free for item in CATALOG if item.slot == slot), slot

    def test_the_default_avatar_is_free_and_valid(self):
        assert validate_avatar(DEFAULT_AVATAR, set()) == DEFAULT_AVATAR

    def test_every_rarity_has_items(self):
        assert {item.rarity for item in PAID} == {rarity for rarity, _ in RARITY_FLOORS}

    def test_effects_always_move_and_only_mythicals_move_elsewhere(self):
        # Banners are the exception: animated ones are sold at legendary and below too.
        for item in PAID:
            if item.slot == "effect":
                assert item.motion >= 1, item.id
            elif item.motion and item.slot != "banner":
                assert item.rarity == "mythical", item.id


class TestPricingIndex:
    def test_free_items_cost_nothing(self):
        assert all(item.price == 0 for item in CATALOG if item.free)

    def test_rarity_follows_the_price_floors(self):
        for item in PAID:
            expected = next(rarity for rarity, floor in RARITY_FLOORS if item.price >= floor)
            assert item.rarity == expected, item.id

    def test_static_items_keep_the_original_index_bands(self):
        for item in STATIC:
            expected = next(rarity for rarity, top in INDEX_BANDS if item.index < top)
            assert item.rarity == expected, item.id

    def test_price_never_falls_as_the_index_rises_at_the_same_motion(self):
        for motion in {item.motion for item in PAID}:
            ordered = sorted((item for item in PAID if item.motion == motion), key=lambda i: i.index)
            for earlier, later in zip(ordered, ordered[1:]):
                assert earlier.price <= later.price, (earlier.id, later.id)

    def test_motion_only_ever_raises_the_price(self):
        for item in PAID:
            still = item.__class__(**{**item.__dict__, "motion": 0})
            assert item.price >= still.price, item.id

    def test_equal_scores_mean_equal_prices(self):
        by_scores = {}
        for item in PAID:
            key = (*(getattr(item, score) for score in WEIGHTS), item.motion)
            by_scores.setdefault(key, set()).add((item.price, item.rarity))
        assert all(len(outcomes) == 1 for outcomes in by_scores.values())

    def test_rarer_tiers_always_cost_more(self):
        floors, ceilings = {}, {}
        for item in PAID:
            floors[item.rarity] = min(floors.get(item.rarity, 10**9), item.price)
            ceilings[item.rarity] = max(ceilings.get(item.rarity, 0), item.price)
        order = ["common", "rare", "epic", "legendary", "mythical"]
        for lower, higher in zip(order, order[1:]):
            assert ceilings[lower] < floors[higher], (lower, higher)

    def test_prices_land_on_round_numbers(self):
        assert all(item.price % 5 == 0 for item in PAID)

    def test_mythicals_are_fully_animated_and_cost_at_least_1500(self):
        mythicals = [item for item in PAID if item.rarity == "mythical"]
        assert len(mythicals) >= 2
        for item in mythicals:
            assert item.motion == 5, item.id
            assert item.price >= 1500, item.id

    def test_fire_is_the_most_expensive_item_below_mythical(self):
        below = [item for item in PAID if item.rarity != "mythical"]
        assert max(below, key=lambda item: item.price).id == "effect_fire"


class TestBundles:
    def test_bundles_are_well_formed(self):
        assert len(BUNDLES_BY_ID) == len(BUNDLES)
        for bundle in BUNDLES:
            assert len(bundle.items) >= 2
            assert len(set(bundle.items)) == len(bundle.items)
            for item_id in bundle.items:
                assert item_id in ITEMS and not ITEMS[item_id].free, (bundle.id, item_id)

    def test_a_bundle_is_cheaper_than_its_parts(self):
        for bundle in BUNDLES:
            assert bundle.price_for(set()) == round_price(BUNDLE_DISCOUNT * bundle.full_price)
            assert bundle.price_for(set()) < bundle.full_price

    def test_owned_items_come_off_the_bundle_price(self):
        knight = BUNDLES_BY_ID["bundle_knight"]
        helmet = ITEMS["head_knight"].price
        assert knight.price_for({"top_armour"}) == round_price(BUNDLE_DISCOUNT * helmet)
        assert knight.price_for(set(knight.items)) == 0

    def test_bundle_rarity_is_its_rarest_item(self):
        assert BUNDLES_BY_ID["bundle_knight"].rarity == "legendary"
        assert BUNDLES_BY_ID["bundle_pirate"].rarity == "epic"


class TestValidateAvatar:
    def test_fills_missing_required_slots_with_defaults(self):
        clean = validate_avatar({"skin": "skin_6"}, set())
        assert clean["skin"] == "skin_6"
        assert clean["hair"] == DEFAULT_AVATAR["hair"]
        assert clean["head"] is None

    def test_rejects_unknown_items_and_wrong_slots(self):
        with pytest.raises(ValueError):
            validate_avatar({"hair": "hair_nope"}, set())
        with pytest.raises(ValueError):
            validate_avatar({"hair": "skin_1"}, set())

    def test_paid_items_need_to_be_owned(self):
        with pytest.raises(ValueError, match="own"):
            validate_avatar({"head": "head_crown"}, set())
        assert validate_avatar({"head": "head_crown"}, {"head_crown"})["head"] == "head_crown"

    def test_optional_slots_can_be_cleared_and_old_keys_are_dropped(self):
        clean = validate_avatar({"effect": None, "prop": "prop_fire"}, set())
        assert clean["effect"] is None
        assert "prop" not in clean

    def test_a_saved_avatar_survives_items_leaving_the_catalog(self):
        # A renamed or retired item must not break every later save of the avatar.
        saved = {"skin": "skin_6", "hair": "hair_retired", "banner": "banner_contender", "prop": "x"}
        clean = stored_avatar(saved)
        assert clean["skin"] == "skin_6"
        assert clean["hair"] == DEFAULT_AVATAR["hair"] and clean["banner"] is None
        assert "prop" not in clean and set(clean) == set(SLOTS)
        assert stored_avatar(None) == DEFAULT_AVATAR
        assert validate_avatar(clean, set()) == clean


class TestBannersAndTheRoad:
    def test_earned_items_have_no_price_and_a_stated_tier(self):
        assert len(EARNED) >= 9
        for item in EARNED:
            assert item.price == 0 and not item.purchasable and item.tier in RARITY_COLORS, item.id
            assert item.slot == "banner" or item.source == "achievement", item.id

    def test_banners_for_sale_span_the_tiers_with_an_animated_mythical(self):
        for_sale = [item for item in PAID if item.slot == "banner"]
        tiers = {item.rarity for item in for_sale}
        assert {"common", "rare", "epic", "legendary", "mythical"} <= tiers
        assert sum(item.rarity == "legendary" for item in for_sale) >= 1
        mythical = [item for item in for_sale if item.rarity == "mythical"]
        assert mythical and all(item.motion == 5 and item.price >= 1500 for item in mythical)

    def test_the_road_runs_upward_and_unlocks_by_standing(self):
        from server.cosmetics import RESERVED, TROPHY_ROAD, unlocked_for

        levels = [item.unlock[1] for item in TROPHY_ROAD if item.unlock[0] == "level"]
        prestige = [item.unlock[1] for item in TROPHY_ROAD if item.unlock[0] == "prestige"]
        assert levels == sorted(levels) and prestige == sorted(prestige)
        assert len(levels) >= 4 and len(prestige) >= 3
        assert unlocked_for(1, 0) == set()
        assert unlocked_for(4, 0) == {"banner_luck", "banner_suspect"}
        assert "banner_spoton" in unlocked_for(1, 500) and "banner_reckoning" not in unlocked_for(1, 500)
        # The top of each road is mythical and animated; the reserved ones can't be unlocked at all.
        assert ITEMS["banner_oracle"].rarity == "mythical" and ITEMS["banner_oracle"].motion == 5
        assert ITEMS["banner_crystal"].rarity == "mythical"
        assert all(item.source in ("tournament", "live") and item.unlock is None for item in RESERVED)
        assert not any(item.id in unlocked_for(99, 10**6) for item in RESERVED)

    def test_an_unlocked_banner_is_wearable_and_a_locked_one_is_not(self):
        from server.cosmetics import unlocked_for

        with pytest.raises(ValueError, match="earned"):
            validate_avatar({"banner": "banner_knowitall"}, set())
        wearable = unlocked_for(7, 0)
        assert validate_avatar({"banner": "banner_knowitall"}, wearable)["banner"] == "banner_knowitall"

    def test_the_road_payload_marks_what_is_unlocked(self):
        from server.cosmetics import road_payload

        road = road_payload(level=4, prestige=160)
        assert [m["unlocked"] for m in road["levels"]][:3] == [True, True, False]
        assert road["prestige"][0]["unlocked"] is True and road["prestige"][1]["unlocked"] is False
        assert all(m["item"]["earned"] for m in road["levels"] + road["prestige"])
        assert {r["source"] for r in road["reserved"]} == {"tournament", "live"}


def test_the_payload_carries_what_the_client_draws_from():
    payload = catalog_payload()
    assert [slot["id"] for slot in payload["slots"]] == list(SLOTS)
    crown = next(item for item in payload["items"] if item["id"] == "head_crown")
    assert crown["rarity"] == "legendary" and crown["price"] == 425
    assert set(payload["rarity_colors"]) == {"common", "rare", "epic", "legendary", "mythical"}
    assert payload["welcome_coins"] == WELCOME_COINS
    knight = next(bundle for bundle in payload["bundles"] if bundle["id"] == "bundle_knight")
    assert knight["price"] < knight["full_price"]


TOP_TIERS = ("legendary", "mythical")
STYLES = ART_DIR.parent / "styles.module.css"


@pytest.mark.skipif(not ART_DIR.exists(), reason="client art not written yet")
class TestTheTopTiersMoveOnEveryPage:
    """Calm routes (the host screen, the phone's game view, leaderboards) hold animation still,
    except for legendary and mythical items (Ryan, Nov 17, 2026)."""

    def test_only_legendary_and_mythical_banners_have_a_light_pass(self):
        # Banners aren't calmed at all, so the stylesheet's list of animated banners has to be
        # exactly the catalog's moving banners, and every one of them a top tier.
        import re

        animated = set(re.findall(r"\.b_(banner_\w+)::after", STYLES.read_text(encoding="utf-8")))
        moving = {item.id for item in CATALOG if item.slot == "banner" and item.motion}
        assert animated == moving
        assert [item_id for item_id in sorted(moving) if ITEMS[item_id].rarity not in TOP_TIERS] == []

    def test_calm_routes_leave_lively_art_alone(self):
        import re

        css = STYLES.read_text(encoding="utf-8")
        calmed = re.findall(r"^\.calm \.[^,{\n]+", css, flags=re.MULTILINE)
        assert len(calmed) >= 10
        assert [selector for selector in calmed if ":not(.lively *)" not in selector] == []
        avatar = (ART_DIR / "Avatar.tsx").read_text(encoding="utf-8")
        assert 'rarity === "legendary" || rarity === "mythical"' in avatar and "styles.lively" in avatar

    def test_which_moving_items_that_frees(self):
        # The effects and outfit that now move during a game, so a catalog change that adds to
        # them is a decision and not an accident. The two epic effects stay calm there.
        moving = {item.id: item.rarity for item in CATALOG if item.motion and item.slot != "banner"}
        assert {item_id for item_id, rarity in moving.items() if rarity in TOP_TIERS} == {
            "effect_cash", "effect_fire", "effect_void", "top_galaxy_armour",
        }
        assert {item_id for item_id, rarity in moving.items() if rarity not in TOP_TIERS} == {
            "effect_sparkles", "effect_lightning",
        }


@pytest.mark.skipif(not ART_DIR.exists(), reason="client art not written yet")
def test_the_client_can_draw_every_item():
    # parts.tsx holds the static art, effects.tsx the animated items.
    source = "\n".join(path.read_text(encoding="utf-8") for path in ART_DIR.glob("*.tsx"))
    drawn = {item.id for item in CATALOG if item.color is None or item.slot in ("top", "head")}
    missing = sorted(item_id for item_id in drawn if f'"{item_id}"' not in source)
    assert missing == []
