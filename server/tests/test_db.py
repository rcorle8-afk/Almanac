from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from server import db as db_module
from server.cosmetics import DEFAULT_AVATAR, WELCOME_COINS
from server.db import (
    COINS_FOR_FINISHING,
    COINS_FOR_WINNING,
    COINS_PER_BEST_QUOTE,
    Database,
    GameResult,
    coins_for,
)


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


def result(user_id=1, points="100", positive="120", rank=1, best=0, trades=0, name="Ryan"):
    return GameResult(
        user_id=user_id,
        name=name,
        points=Decimal(points),
        positive_points=Decimal(positive),
        rank=rank,
        best_quotes=best,
        trades=trades,
    )


class TestSignIn:
    def test_first_sign_in_creates_the_user_and_a_session(self, db):
        user, token = db.sign_in_google("g1", "ryan@example.com", "Ryan", "pic.png")
        assert user["name"] == "Ryan"
        assert user["coins"] == WELCOME_COINS
        assert db.user_for_session(token)["id"] == user["id"]

    def test_the_welcome_coins_come_once(self, db):
        user, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        db.buy(user["id"], "ears_studs", 20)
        again, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        assert again["coins"] == WELCOME_COINS - 20

    def test_signing_in_again_reuses_the_user_and_refreshes_the_name(self, db):
        first, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        second, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan C")
        assert first["id"] == second["id"]
        assert second["name"] == "Ryan C"

    def test_each_sign_in_gets_its_own_session(self, db):
        _, phone = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        _, laptop = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        assert phone != laptop
        db.sign_out(phone)
        assert db.user_for_session(phone) is None
        assert db.user_for_session(laptop) is not None

    @pytest.mark.parametrize("token", [None, "", "nope"])
    def test_unknown_tokens_give_nobody(self, db, token):
        assert db.user_for_session(token) is None

    def test_expired_sessions_are_ignored(self, db):
        user, token = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        db.conn.execute("UPDATE sessions SET expires_at = ? WHERE token = ?", (past, token))
        assert db.user_for_session(token) is None

    def test_two_people_are_two_users(self, db):
        a, _ = db.sign_in_google("g1", "a@example.com", "A")
        b, _ = db.sign_in_google("g2", "b@example.com", "B")
        assert a["id"] != b["id"]


class TestCoins:
    def test_winner_with_best_quotes(self):
        earned = coins_for(result(positive="130", rank=1, best=2))
        assert earned == 130 + COINS_FOR_FINISHING + COINS_FOR_WINNING + 2 * COINS_PER_BEST_QUOTE

    def test_a_losing_player_still_gets_the_finishing_coins(self):
        assert coins_for(result(points="-80", positive="0", rank=4)) == COINS_FOR_FINISHING

    def test_fractional_points_round_down(self):
        assert coins_for(result(positive="69.31", rank=2)) == 69 + COINS_FOR_FINISHING


class TestRecord:
    def test_a_game_is_stored_and_coins_paid(self, db):
        user, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        awarded = db.record_game(
            "ATOM", 7, 4, [result(user_id=user["id"], positive="130", rank=1, best=2, trades=5)]
        )
        assert awarded[user["id"]].coins == 220
        profile = db.profile(user["id"])
        assert profile["user"]["coins"] == WELCOME_COINS + 220
        assert (profile["games"], profile["wins"], profile["best_quotes"], profile["trades"]) == (1, 1, 2, 5)
        assert profile["total_points"] == "100"
        assert profile["recent"][0]["room_code"] == "ATOM"
        assert profile["recent"][0]["rank"] == 1
        assert profile["recent"][0]["player_count"] == 4

    def test_the_profile_sums_across_games(self, db):
        user, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        db.record_game("ATOM", 7, 3, [result(user_id=user["id"], points="100", rank=1)])
        db.record_game("VEGA", 7, 3, [result(user_id=user["id"], points="-40.5", positive="0", rank=3)])
        profile = db.profile(user["id"])
        assert profile["games"] == 2
        assert profile["wins"] == 1
        assert profile["total_points"] == "59.5"
        assert [game["room_code"] for game in profile["recent"]] == ["VEGA", "ATOM"]
        assert profile["user"]["coins"] == WELCOME_COINS + (120 + 20 + 50) + 20

    def test_xp_and_prestige_accrue_and_levels_follow(self, db):
        user, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        assert (user["xp"], user["prestige"], user["level"], user["next_level_xp"]) == (0, 0, 1, 100)
        award = db.record_game("ATOM", 7, 4, [result(user_id=user["id"], rank=1, best=2, trades=5)])[user["id"]]
        # 50 for finishing + 5 x 7 rounds + 2 x 5 trades + 15 x 2 Best Quotes
        assert award.xp == 50 + 35 + 10 + 30
        assert award.prestige == 100 + 2 * 20
        assert (award.level_before, award.level_after, award.level_up) == (1, 2, 2)
        after = db.profile(user["id"])["user"]
        assert (after["xp"], after["prestige"], after["level"], after["next_level_xp"]) == (125, 140, 2, 400)
        third = db.record_game("VEGA", 7, 4, [result(user_id=user["id"], rank=3)])[user["id"]]
        assert third.prestige == 30 and third.level_up is None
        assert db.profile(user["id"])["recent"][0]["xp"] == third.xp

    def test_games_saved_before_progression_are_credited_once(self, tmp_path):
        path = tmp_path / "old.db"
        db = Database(path)
        user, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        db.record_game("ATOM", 7, 4, [result(user_id=user["id"], rank=1, best=2, trades=5)])
        for table, column in (("results", "xp"), ("results", "prestige"), ("users", "xp"), ("users", "prestige")):
            db.conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")  # a database from before M4
        db.conn.close()
        reopened = Database(path)
        after = reopened.profile(user["id"])["user"]
        assert (after["xp"], after["prestige"], after["level"]) == (125, 140, 2)
        assert reopened.profile(user["id"])["recent"][0]["xp"] == 125
        reopened.conn.close()
        again = Database(path)  # the columns exist now, so nothing is credited twice
        assert again.profile(user["id"])["user"]["xp"] == 125

    def test_levels_grow_with_the_square_of_xp(self):
        from server.db import level_for, xp_for_level

        assert [level_for(xp) for xp in (0, 99, 100, 399, 400, 900, 1599, 1600)] == [1, 1, 2, 2, 3, 4, 4, 5]
        assert [xp_for_level(level) for level in (1, 2, 3, 5)] == [0, 100, 400, 1600]

    def test_only_the_players_in_the_game_are_paid(self, db):
        a, _ = db.sign_in_google("g1", "a@example.com", "A")
        b, _ = db.sign_in_google("g2", "b@example.com", "B")
        db.record_game("ATOM", 7, 2, [result(user_id=a["id"], rank=1)])
        assert db.profile(b["id"])["user"]["coins"] == WELCOME_COINS
        assert db.profile(b["id"])["games"] == 0

    def test_an_unknown_user_has_no_profile(self, db):
        assert db.profile(999) is None


class TestLocker:
    def test_a_purchase_is_atomic(self, db):
        user, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        updated = db.buy(user["id"], "eye_goggles", 135)
        assert updated["coins"] == WELCOME_COINS - 135
        assert db.inventory(user["id"]) == ["eye_goggles"]

    def test_too_few_coins_changes_nothing(self, db):
        user, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        with pytest.raises(ValueError, match="more coins"):
            db.buy(user["id"], "effect_void", 1750)  # above the welcome coins
        assert db.inventory(user["id"]) == []
        assert db.profile(user["id"])["user"]["coins"] == WELCOME_COINS

    def test_an_item_is_bought_once(self, db):
        user, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        db.buy(user["id"], "ears_studs", 20)
        with pytest.raises(ValueError, match="already"):
            db.buy(user["id"], "ears_studs", 20)
        assert db.profile(user["id"])["user"]["coins"] == WELCOME_COINS - 20

    def test_a_bundle_is_all_or_nothing(self, db):
        user, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        db.buy(user["id"], "head_hardhat", 225)
        with pytest.raises(ValueError, match="already"):
            db.buy_many(user["id"], {"head_hardhat": 180, "top_hivis": 195}, 375)
        assert db.inventory(user["id"]) == ["head_hardhat"]
        assert db.profile(user["id"])["user"]["coins"] == WELCOME_COINS - 225
        updated = db.buy_many(user["id"], {"top_hivis": 195}, 100)
        assert updated["coins"] == WELCOME_COINS - 225 - 100
        assert db.inventory(user["id"]) == ["head_hardhat", "top_hivis"]

    def test_the_avatar_is_saved_and_defaults_until_then(self, db):
        user, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        assert user["avatar"]["skin"] == "skin_3"
        updated = db.set_avatar(user["id"], {**user["avatar"], "skin": "skin_6"})
        assert updated["avatar"]["skin"] == "skin_6"
        assert db.profile(user["id"])["user"]["avatar"]["skin"] == "skin_6"

    def test_old_databases_gain_the_avatar_column(self, tmp_path):
        import sqlite3

        path = tmp_path / "old.db"
        old = sqlite3.connect(path)
        old.executescript(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, google_sub TEXT NOT NULL UNIQUE, "
            "email TEXT NOT NULL, name TEXT NOT NULL, picture TEXT NOT NULL DEFAULT '', "
            "coins INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);"
            "INSERT INTO users (google_sub, email, name, created_at) VALUES ('g1', 'a@b.c', 'Old', 'x');"
        )
        old.close()
        db = Database(path)
        assert db.profile(1)["user"]["avatar"] == DEFAULT_AVATAR


class TestRetiredItems:
    def test_a_retired_item_is_refunded_at_startup(self, tmp_path):
        path = tmp_path / "retire.db"
        first = Database(path)
        user, _ = first.sign_in_google("g1", "ryan@example.com", "Ryan")
        first.conn.execute("UPDATE users SET coins = 2000 WHERE id = ?", (user["id"],))
        first.buy(user["id"], "effect_phoenix", 1750)
        first.buy(user["id"], "ears_studs", 20)
        assert first.profile(user["id"])["user"]["coins"] == 230
        first.conn.close()
        # The next start, with the item retired, hands the coins back and keeps everything else.
        second = Database(path)
        assert second.profile(user["id"])["user"]["coins"] == 1980
        assert second.inventory(user["id"]) == ["ears_studs"]
        # And a start after that changes nothing.
        second.conn.close()
        third = Database(path)
        assert third.profile(user["id"])["user"]["coins"] == 1980

    def test_a_renamed_item_follows_its_owner(self, tmp_path):
        path = tmp_path / "rename.db"
        first = Database(path)
        user, _ = first.sign_in_google("g1", "ryan@example.com", "Ryan")
        first.buy(user["id"], "banner_slate", 60)
        first.set_avatar(user["id"], {**DEFAULT_AVATAR, "banner": "banner_slate"})
        first.conn.close()
        second = Database(path)
        assert second.inventory(user["id"]) == ["banner_ballpark"]
        assert second.profile(user["id"])["user"]["avatar"]["banner"] == "banner_ballpark"
        assert second.profile(user["id"])["user"]["coins"] == WELCOME_COINS - 60

    def test_an_item_made_free_is_refunded_at_startup(self, tmp_path):
        # Side part cost 25 coins until Nov 4, 2026; its buyers get them back once it's free.
        path = tmp_path / "free.db"
        first = Database(path)
        user, _ = first.sign_in_google("g1", "ryan@example.com", "Ryan")
        first.conn.execute(
            "INSERT INTO inventory (user_id, item_id, price, bought_at) VALUES (?, 'hair_side_part', 25, '2026-11-03T00:00:00Z')",
            (user["id"],),
        )
        first.conn.execute("UPDATE users SET coins = coins - 25 WHERE id = ?", (user["id"],))
        first.conn.close()
        second = Database(path)
        assert second.profile(user["id"])["user"]["coins"] == WELCOME_COINS
        assert second.inventory(user["id"]) == []


class TestCoinGrants:
    """A one-off gift of coins to every account (Ryan, Nov 17, 2026: 800 to everyone)."""

    def coins(self, db, user):
        return db.profile(user["id"])["user"]["coins"]

    def before_the_grant(self, path, monkeypatch):
        """A database as the live one was: accounts already there, the grant not yet thought of."""
        monkeypatch.setattr(db_module, "COIN_GRANTS", {})
        db = Database(path)
        ann, _ = db.sign_in_google("g1", "ann@example.com", "Ann")
        ben, _ = db.sign_in_google("g2", "ben@example.com", "Ben")
        db.buy(ben["id"], "ears_studs", 20)
        db.conn.close()
        return ann, ben

    def test_every_account_gets_it_once(self, tmp_path, monkeypatch):
        path = tmp_path / "grant.db"
        ann, ben = self.before_the_grant(path, monkeypatch)
        monkeypatch.setattr(db_module, "COIN_GRANTS", {"2026-11-17-everyone": 800})
        db = Database(path)  # the first start with the grant pays it
        assert (self.coins(db, ann), self.coins(db, ben)) == (WELCOME_COINS + 800, WELCOME_COINS - 20 + 800)
        [row] = db.conn.execute("SELECT id, coins, accounts FROM coin_grants").fetchall()
        assert tuple(row) == ("2026-11-17-everyone", 800, 2)
        db.conn.close()
        for _ in range(2):  # and every start after that leaves the balances alone
            db = Database(path)
            assert (self.coins(db, ann), self.coins(db, ben)) == (WELCOME_COINS + 800, WELCOME_COINS - 20 + 800)
            db.conn.close()

    def test_an_account_made_afterwards_does_not_get_it(self, tmp_path, monkeypatch):
        path = tmp_path / "later.db"
        self.before_the_grant(path, monkeypatch)
        monkeypatch.setattr(db_module, "COIN_GRANTS", {"2026-11-17-everyone": 800})
        db = Database(path)
        cat, _ = db.sign_in_google("g3", "cat@example.com", "Cat")
        db.conn.close()
        db = Database(path)
        assert self.coins(db, cat) == WELCOME_COINS
        assert db.conn.execute("SELECT accounts FROM coin_grants").fetchone()[0] == 2

    def test_a_second_grant_is_paid_on_top_of_the_first(self, tmp_path, monkeypatch):
        path = tmp_path / "two.db"
        ann, _ = self.before_the_grant(path, monkeypatch)
        monkeypatch.setattr(db_module, "COIN_GRANTS", {"first": 800})
        Database(path).conn.close()
        monkeypatch.setattr(db_module, "COIN_GRANTS", {"first": 800, "second": 100})
        db = Database(path)
        assert self.coins(db, ann) == WELCOME_COINS + 900
        assert [row["id"] for row in db.conn.execute("SELECT id FROM coin_grants ORDER BY applied_at, id")] == ["first", "second"]

    def test_the_grant_being_paid_now_is_800_to_everyone(self):
        assert db_module.COIN_GRANTS == {"2026-11-17-everyone": 800}

    def test_a_new_database_records_it_as_paid_to_nobody(self, db):
        user, _ = db.sign_in_google("g1", "ryan@example.com", "Ryan")
        assert user["coins"] == WELCOME_COINS  # a new account starts with the welcome coins alone
        assert [tuple(row) for row in db.conn.execute("SELECT id, accounts FROM coin_grants")] == [("2026-11-17-everyone", 0)]