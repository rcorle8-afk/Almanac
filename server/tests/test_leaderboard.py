"""The global leaderboard (Nov 12, 2026): groups by combined prestige, players by their own."""

import pytest
from fastapi.testclient import TestClient

from server import app as app_module
from server import social
from server.db import Database
from server.tests.test_social import account, app_db, client_for, fake_verify, uid  # noqa: F401  (fixtures)


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "board.db")


def prestige(db, **named):
    """Signs each name up with that much prestige; returns their ids by name."""
    ids = {}
    for name, amount in named.items():
        ids[name] = uid(db, name)
        db.conn.execute("UPDATE users SET prestige = ? WHERE id = ?", (amount, ids[name]))
    return ids


def confirm_cheat(db, user_id):
    db.conn.execute(
        "INSERT INTO accuracy_flags (user_id, status, quotes, bullseyes, baseline, p_value, after_quote_id, "
        "last_quote_id, created_at, updated_at) VALUES (?, 'confirmed', 20, 20, 0.05, 1e-9, 0, 0, 'x', 'x')",
        (user_id,),
    )


class TestPlayers:
    def test_ranked_by_prestige_with_ties_sharing_a_place(self, db):
        ids = prestige(db, Ann=900, Ben=500, Cat=500, Dan=200)
        board = social.leaderboard(db, ids["Dan"])
        assert [(p["name"], p["place"]) for p in board["players"]] == [("Ann", 1), ("Ben", 2), ("Cat", 2), ("Dan", 4)]
        assert [p["you"] for p in board["players"]] == [False, False, False, True]
        assert board["you"] == {"place": 4, "prestige": 200} and board["player_count"] == 4
        assert social.leaderboard(db, ids["Cat"])["you"]["place"] == 2

    def test_nobody_without_prestige_is_ranked(self, db):
        ids = prestige(db, Ann=900, Ben=0)
        board = social.leaderboard(db, ids["Ben"])
        assert [p["name"] for p in board["players"]] == ["Ann"]
        assert board["you"] == {"place": None, "prestige": 0} and board["player_count"] == 1

    def test_only_the_top_come_back_but_your_place_is_still_counted(self, db):
        ids = prestige(db, Ann=900, Ben=700, Cat=500, Dan=300)
        board = social.leaderboard(db, ids["Dan"], limit=2)
        assert [p["name"] for p in board["players"]] == ["Ann", "Ben"]
        assert board["you"]["place"] == 4 and board["player_count"] == 4

    def test_a_confirmed_cheat_is_left_off_and_everyone_moves_up(self, db):
        ids = prestige(db, Ann=900, Ben=500, Cat=200)
        confirm_cheat(db, ids["Ann"])
        board = social.leaderboard(db, ids["Cat"])
        assert [(p["name"], p["place"]) for p in board["players"]] == [("Ben", 1), ("Cat", 2)]
        assert board["you"]["place"] == 2 and board["player_count"] == 2
        assert social.leaderboard(db, ids["Ann"])["you"]["place"] is None

    def test_a_card_never_carries_an_email_or_an_account_id(self, db):
        ids = prestige(db, Ann=900)
        [row] = social.leaderboard(db, ids["Ann"])["players"]
        assert set(row) == {"public_id", "name", "handle", "avatar", "level", "prestige", "place", "you"}


class TestGroups:
    def test_ranked_by_their_members_combined_prestige(self, db):
        ids = prestige(db, Ann=300, Ben=450, Cat=50, Dan=700, Eve=0)
        quants = social.create_group(db, ids["Ann"], "Quants")["public_id"]
        social.join(db, ids["Ben"], quants, via_room=True)
        social.join(db, ids["Cat"], quants, via_room=True)
        solo = social.create_group(db, ids["Dan"], "Solo Desk")["public_id"]
        social.create_group(db, ids["Eve"], "Newcomers")  # no prestige yet: not ranked
        board = social.leaderboard(db, ids["Cat"])
        assert [(g["name"], g["prestige"], g["member_count"], g["place"]) for g in board["groups"]] == [
            ("Quants", 800, 3, 1),
            ("Solo Desk", 700, 1, 2),
        ]
        assert [g["role"] for g in board["groups"]] == ["member", None]
        assert board["group_count"] == 2
        assert board["your_groups"] == [{"place": 1, "public_id": quants, "name": "Quants"}]
        assert social.leaderboard(db, ids["Dan"])["your_groups"] == [{"place": 2, "public_id": solo, "name": "Solo Desk"}]

    def test_your_groups_place_is_given_even_below_the_cut(self, db):
        ids = prestige(db, Ann=900, Ben=500, Cat=100)
        for name, title in (("Ann", "First"), ("Ben", "Second"), ("Cat", "Third")):
            social.create_group(db, ids[name], title)
        board = social.leaderboard(db, ids["Cat"], limit=2)
        assert [g["name"] for g in board["groups"]] == ["First", "Second"] and board["group_count"] == 3
        assert board["your_groups"][0]["place"] == 3

    def test_a_reported_name_and_picture_stay_hidden_on_the_board(self, db):
        from server.tests.test_groups import picture

        ids = prestige(db, Ann=900, Ben=100)
        group = social.create_group(db, ids["Ann"], "Edgy Name")["public_id"]
        social.set_image(db, ids["Ann"], group, picture())
        social.report(db, ids["Ben"], "group_name", group)
        social.report(db, ids["Ben"], "group_image", group)
        [seen] = social.leaderboard(db, ids["Ben"])["groups"]
        assert seen["name"] == social.HIDDEN_GROUP_NAME and seen["icon"]["image"] is None
        [own] = social.leaderboard(db, ids["Ann"])["groups"]
        assert own["name"] == "Edgy Name" and own["icon"]["image"]


class TestPlaces:
    @pytest.mark.parametrize(
        "scores, places",
        [([], []), ([5], [1]), ([9, 5, 5, 2], [1, 2, 2, 4]), ([7, 7, 7], [1, 1, 1]), ([9, 8, 7], [1, 2, 3])],
    )
    def test_equal_scores_share_a_place_and_the_next_skips(self, scores, places):
        assert social._places(scores) == places


class TestApi:
    def test_the_board_needs_a_sign_in(self, app_db):
        assert TestClient(app_module.app).get("/api/leaderboard").status_code == 401

    def test_over_http(self, app_db):
        ann, ben = client_for("Ann"), client_for("Ben")
        app_db.conn.execute("UPDATE users SET prestige = 400 WHERE name = 'Ann'")
        ann.post("/api/groups", json={"name": "Quants"})
        board = ben.get("/api/leaderboard").json()
        assert [p["name"] for p in board["players"]] == ["Ann"] and board["you"]["place"] is None
        assert [(g["name"], g["prestige"], g["role"]) for g in board["groups"]] == [("Quants", 400, None)]
        assert "email" not in str(board)
