from decimal import Decimal

from server import achievements
from server.achievements import ACHIEVEMENTS, BY_ID, HIDDEN, TIERS, due, list_view
from server.cosmetics import CATALOG, ITEMS
from server.db import Database, GameResult
from server.moderation import BIO_LIMIT, clean_bio
from server.protocol import RoomConfig
from server.rooms import Phase, Room, save_game
from server.tests.test_rooms import QUESTIONS, Clock

import pytest


def signed_up(db, name="Ann"):
    user, _ = db.sign_in_google(f"g-{name}", f"{name.lower()}@example.com", name)
    return user


def finish_games(db, user, count, rank=1):
    for _ in range(count):
        db.record_game("ABCD", 3, 2, [GameResult(user["id"], user["name"], Decimal(10), Decimal(10), rank, 0, 0)])


def earned(views):
    return {(view["id"], view["tier"]) for view in views}


class TestDefinitions:
    def test_tiers_run_in_order_and_get_harder_and_richer(self):
        for achievement in ACHIEVEMENTS:
            order = [TIERS.index(tier.tier) for tier in achievement.tiers]
            assert order == sorted(set(order)), achievement.id
            goals = [tier.goal for tier in achievement.tiers if tier.stat is None]
            assert goals == sorted(goals, reverse=achievement.at_most), achievement.id
            coins = [tier.coins for tier in achievement.tiers]
            assert coins == sorted(coins) and min(coins) > 0, achievement.id

    def test_tiers_follow_difficulty_not_a_template(self):
        sizes = {len(achievement.tiers) for achievement in ACHIEVEMENTS}
        assert 5 in sizes and 3 in sizes and 1 in sizes
        assert any(achievement.secret for achievement in ACHIEVEMENTS)

    def test_every_reward_item_is_an_achievement_item_given_once(self):
        given = [tier.item for achievement in ACHIEVEMENTS for tier in achievement.tiers if tier.item]
        assert len(given) == len(set(given))
        assert set(given) == {item.id for item in CATALOG if item.source == "achievement"}
        assert not any(ITEMS[item_id].purchasable for item_id in given)

    def test_rewards_read_plainly_and_hide_names_when_asked(self):
        assert achievements.reward_text(BY_ID["hot_streak"].tiers[2]) == "+250 coins and the On a Roll banner"
        assert achievements.reward_text(BY_ID["regular"].tiers[2]) == "+400 coins and the Mortarboard headwear"
        hidden = achievements.reward_text(BY_ID["comeback"].tiers[0], hide_item=True)
        assert hidden == "+750 coins and a mythical banner"


class TestChecking:
    def test_floors_ceilings_and_tier_stats(self):
        facts = {"game_round_streak": 3, "game_quote_ratio": 1.15, "game_exact_quote": 1, "life_wins": 5}
        reached = {(a.id, t.tier) for a, t in due(facts)}
        assert {("hot_streak", "bronze"), ("hot_streak", "silver")} <= reached
        assert ("hot_streak", "gold") not in reached and ("hot_streak", "mystery") not in reached
        assert {("bullseye", "bronze"), ("bullseye", "silver"), ("bullseye", "mystery")} <= reached
        assert ("bullseye", "gold") not in reached
        assert {("champion", "bronze"), ("champion", "silver")} <= reached

    def test_a_missing_stat_checks_nothing(self):
        assert due({}) == []


class TestAwarding:
    def test_a_tier_pays_once(self, tmp_path):
        db = Database(tmp_path / "a.db")
        user = signed_up(db)
        finish_games(db, user, 1)
        before = db.profile(user["id"])["user"]["coins"]
        first = achievements.award(db, user["id"])
        assert earned(first) == {("champion", "bronze")}
        assert first[0]["reward"] == "+50 coins"
        assert db.profile(user["id"])["user"]["coins"] == before + 50
        assert achievements.award(db, user["id"]) == []
        assert db.profile(user["id"])["user"]["coins"] == before + 50

    def test_an_item_reward_lands_in_the_inventory_for_free(self, tmp_path):
        db = Database(tmp_path / "a.db")
        user = signed_up(db)
        finish_games(db, user, 25)
        got = earned(achievements.award(db, user["id"]))
        assert {("champion", "gold"), ("champion", "mystery"), ("regular", "silver")} <= got
        assert "banner_trophycase" in db.inventory(user["id"])
        assert db.lifetime(user["id"])["life_coins_spent"] == 0  # a gift isn't spending

    def test_the_list_hides_mystery_requirements_until_earned(self, tmp_path):
        db = Database(tmp_path / "a.db")
        user = signed_up(db)
        finish_games(db, user, 2)
        rows = {row["id"]: row for row in list_view(db, user["id"])["achievements"]}
        assert rows["hot_streak"]["tiers"][-1]["requirement"] == HIDDEN
        assert rows["comeback"]["name"] == "Secret achievement"
        assert rows["comeback"]["tiers"][0] == {
            "tier": "mystery",
            "requirement": HIDDEN,
            "reward": "+750 coins and a mythical banner",
            "goal": None,
            "earned_at": None,
        }
        assert rows["champion"]["progress"] == 2 and rows["bullseye"]["progress"] is None
        db.award_achievements(user["id"], [("comeback", "mystery", 750, "banner_comeback")])
        view = list_view(db, user["id"])
        rows = {row["id"]: row for row in view["achievements"]}
        assert rows["comeback"]["name"] == "Comeback Kid"
        assert rows["comeback"]["tiers"][0]["requirement"].startswith("Win a game after")
        assert rows["comeback"]["tiers"][0]["earned_at"] is not None
        assert view["earned"] == 1 and view["total"] == sum(len(a.tiers) for a in ACHIEVEMENTS)


class TestGameFacts:
    def test_a_perfect_game_earns_its_feats_and_shows_them_at_the_end(self, tmp_path):
        db = Database(tmp_path / "a.db")
        ann = signed_up(db)
        room = Room("ABCD", RoomConfig(rounds=7), QUESTIONS, Clock())
        a = room.join("", user=ann)
        b = room.join("Ben")
        room.join("Cy")
        room.start()
        while room.phase is not Phase.GAME_OVER:
            if room.phase is Phase.QUOTING:
                room.submit_quote(a, Decimal(100), Decimal(101))  # holds the answer (100), 1% wide
                room.submit_quote(b, Decimal(50), Decimal(150))
            room.advance()
        facts = room.game_facts(a, rank=1)
        assert facts["game_round_streak"] == 7 and facts["game_clean_sweep"] == 1
        assert facts["game_exact_quote"] == 1 and facts["game_quote_ratio"] == pytest.approx(1.01)
        save_game(db, room)
        got = earned(a.achievements)
        assert {("hot_streak", "platinum"), ("hot_streak", "mystery"), ("bullseye", "platinum")} <= got
        assert {("bullseye", "mystery"), ("champion", "bronze")} <= got
        you = room.snapshot(a).you
        assert {(e.id, e.tier) for e in you.achievements} == got
        assert "banner_onaroll" in db.inventory(ann["id"])

    def test_a_comeback_from_last_at_halfway(self):
        room = Room("ABCD", RoomConfig(rounds=3), QUESTIONS, Clock())
        a, b, c = (room.join(name) for name in ("Ann", "Ben", "Cy"))
        room.start()
        while room.phase is not Phase.GAME_OVER:
            if room.phase is Phase.QUOTING:
                # Ben takes the first round's Best Quote; Ann takes the last two.
                tight, loose = (b, a) if room.round_no == 1 else (a, b)
                room.submit_quote(tight, Decimal(99), Decimal(101))
                room.submit_quote(loose, Decimal(50), Decimal(150))
            room.advance()
        assert a.id in room.last_at_halfway
        assert room.game_facts(a, rank=1)["game_comeback"] == 1
        assert room.game_facts(b, rank=2)["game_comeback"] == 0

    def test_a_tied_round_goes_to_nobody(self):
        room = Room("ABCD", RoomConfig(rounds=3), QUESTIONS, Clock())
        a, b = room.join("Ann"), room.join("Ben")
        room.start()
        while room.phase is not Phase.SCORES:
            room.advance()  # nobody quotes: everyone scores zero
        assert room.round_wins[a.id] == room.round_wins[b.id] == 0


class TestBio:
    def test_a_bio_is_trimmed_and_capped(self):
        assert clean_bio("  Market   maker,\nmostly  ") == "Market maker, mostly"
        with pytest.raises(ValueError, match="160"):
            clean_bio("x" * (BIO_LIMIT + 1))

    @pytest.mark.parametrize("text", ["what the fuck", "total SH1T trader", "b!tch"])
    def test_blocked_words_are_refused_even_disguised(self, text):
        with pytest.raises(ValueError, match="word"):
            clean_bio(text)

    def test_ordinary_words_that_contain_one_pass(self):
        assert clean_bio("Scunthorpe classic, cocktail hour") == "Scunthorpe classic, cocktail hour"


def test_a_level_table_at_halfway_has_nobody_in_last_place():
    room = Room("ABCD", RoomConfig(rounds=3), QUESTIONS, Clock())
    a, b, c = (room.join(name) for name in ("Ann", "Ben", "Cy"))
    room.start()
    while room.phase is not Phase.GAME_OVER:
        room.advance()  # nobody quotes: everyone stays at zero
    assert room.last_at_halfway == set()
    assert room.game_facts(a, rank=1)["game_comeback"] == 0

class TestGameLog:
    def test_a_saved_game_keeps_the_table_the_rounds_and_your_trades(self, tmp_path):
        from server.engine.models import Side

        db = Database(tmp_path / "log.db")
        ann = signed_up(db)
        room = Room("ABCD", RoomConfig(rounds=3), QUESTIONS, Clock())
        a = room.join("", user=ann)
        b = room.join("Ben")
        room.set_bots(1, 1)
        room.start()
        while room.phase is not Phase.GAME_OVER:
            if room.phase is Phase.TRADING and room.round_no == 2:
                room.place_order(b, Side.SELL, Decimal(80), 2)
                room.place_order(a, Side.BUY, Decimal(80), 2)  # Ann buys 2 at 80 from Ben; answer 100
            room.advance()
        save_game(db, room)
        [game] = db.profile(ann["id"])["recent"]
        detail = db.game_detail(ann["id"], game["game_id"])
        assert detail["detailed"] is True
        names = {p["name"]: p for p in detail["players"]}
        assert set(names) == {"Ann", "Ben", "Bot Ada"}
        assert names["Ann"]["you"] and names["Ann"]["signed_in"] and not names["Ben"]["signed_in"]
        assert names["Bot Ada"]["bot"] and names["Ann"]["rank"] == 1
        assert [r["round_no"] for r in detail["rounds"]] == [1, 2, 3]
        assert detail["rounds"][1]["question"] == room.questions[1].text and detail["rounds"][1]["answer"] == "100"
        [fill] = detail["rounds"][1]["fills"]
        assert (fill["side"], fill["price"], fill["size"], fill["counterparty"]) == ("BUY", "80", 2, "Ben")
        assert Decimal(fill["points"]) == Decimal("44.63")  # 2 x 100 ln(100/80)
        assert detail["rounds"][0]["fills"] == []
        [row] = db.history(ann["id"])["games"]
        assert "Ann" in row["winners"].split(", ") and row["trades"] >= 1

    def test_the_history_pages_through_every_game_newest_first(self, tmp_path):
        db = Database(tmp_path / "log.db")
        ann, ben = signed_up(db), signed_up(db, "Ben")
        finish_games(db, ann, 5)
        finish_games(db, ben, 1)  # not Ann's
        pages = [db.history(ann["id"], limit=2)]
        while pages[-1]["next"] is not None:
            pages.append(db.history(ann["id"], before=pages[-1]["next"], limit=2))
        ids = [game["game_id"] for page in pages for game in page["games"]]
        assert [len(page["games"]) for page in pages] == [2, 2, 1]
        assert ids == sorted(ids, reverse=True) and len(set(ids)) == 5
        assert all(page["total"] == 5 for page in pages)
        assert pages[0]["games"][0]["winners"] == ""  # saved without a table
        assert db.history(ben["id"])["total"] == 1

    def test_only_players_of_a_game_can_open_it_and_old_games_say_so(self, tmp_path):
        db = Database(tmp_path / "log.db")
        ann, ben = signed_up(db), signed_up(db, "Ben")
        finish_games(db, ann, 1)  # saved the old way: a result, no table or trades
        [game] = db.profile(ann["id"])["recent"]
        old = db.game_detail(ann["id"], game["game_id"])
        assert old["detailed"] is False and old["players"] == [] and old["game"]["rank"] == 1
        assert db.game_detail(ben["id"], game["game_id"]) is None