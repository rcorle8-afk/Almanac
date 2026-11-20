"""The players page (Ryan, Nov 17, 2026): every signed-in account with its standing and record,
who may see it, and the Excel file."""

import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from server import app as app_module
from server import players, social
from server.db import Database, EndlessResult, GameResult, RoundRecord
from server.tests.test_social import account, app_db, client_for, fake_verify, uid  # noqa: F401  (fixtures)


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "players.db")


def game(db, *placings, live=False):
    """Saves a three-round game: (user id, name, rank, best quotes, trades) for each player."""
    results = [
        GameResult(user, name, Decimal(100 - 30 * rank), Decimal(max(0, 100 - 30 * rank)), rank, quotes, trades)
        for user, name, rank, quotes, trades in placings
    ]
    db.record_game("ABCD", 3, len(results), results, live=live)


def row(report, name):
    return next(player for player in report["players"] if player["name"] == name)


class TestTheReport:
    def test_each_account_has_its_standing_and_record(self, db):
        ann, ben, cat = (uid(db, name) for name in ("Ann", "Ben", "Cat"))
        game(db, (ann, "Ann", 1, 2, 9), (ben, "Ben", 2, 0, 4))
        game(db, (ann, "Ann", 4, 0, 3), (ben, "Ben", 1, 1, 6), live=True)
        report = players.report(db, full=False)
        a, b, c = row(report, "Ann"), row(report, "Ben"), row(report, "Cat")
        assert (a["games"], a["wins"], a["podiums"], a["best_quotes"], a["trades"]) == (2, 1, 1, 2, 12)
        assert (b["games"], b["wins"], b["podiums"], b["live_games"]) == (2, 2 - 1, 2, 1)
        assert a["points"] == 70 - 20 and a["live_games"] == 1
        # Standing is the account's own: what the games paid, read straight from it.
        stored = db._fetch_user(ann)
        assert (a["xp"], a["prestige"], a["coins"], a["level"]) == (stored["xp"], stored["prestige"], stored["coins"], stored["level"])
        assert a["prestige"] > 0 and a["last_played"] is not None and a["joined"]
        # Someone who has only signed up is still listed, with an empty record.
        assert (c["games"], c["wins"], c["last_played"], c["open_rounds"], c["groups"]) == (0, 0, None, 0, [])
        assert [p["name"] for p in report["players"]][-1] == "Cat"  # ranked by prestige, then XP

    def test_open_table_rounds_are_counted_apart_from_games(self, db):
        ann = uid(db, "Ann")
        for _ in range(3):
            db.record_endless_round(
                "OPEN", RoundRecord(1, "How many?", "widgets", Decimal(100)), 4,
                [EndlessResult(ann, Decimal(12), Decimal(12), Decimal(0), 2, False)],
            )
        report = players.report(db, full=False)
        a = row(report, "Ann")
        assert (a["games"], a["open_rounds"]) == (0, 3) and a["last_played"] is not None
        assert (report["summary"]["games"], report["summary"]["open_rounds"]) == (0, 3)

    def test_it_counts_what_a_player_owns_and_who_they_know(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        db.conn.execute("INSERT INTO inventory (user_id, item_id, price, bought_at) VALUES (?, 'hat', 150, 'now')", (ann,))
        db.conn.execute("INSERT INTO inventory (user_id, item_id, price, bought_at) VALUES (?, 'tee', 60, 'now')", (ann,))
        db.conn.execute("INSERT INTO achievements (user_id, achievement_id, tier, earned_at) VALUES (?, 'champion', 'bronze', 'now')", (ann,))
        social.send_request(db, ann, ben)
        social.accept_request(db, ben, ann)
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.join(db, ben, group, via_room=True)
        db.conn.execute("UPDATE groups SET name_hidden = 1 WHERE public_id = ?", (social.create_group(db, ann, "Rude name")["public_id"],))
        report = players.report(db, full=False)
        a, b = row(report, "Ann"), row(report, "Ben")
        assert (a["items"], a["coins_spent"], a["badges"], a["friends"]) == (2, 210, 1, 1)
        assert a["groups"] == ["Quants", social.HIDDEN_GROUP_NAME] and b["groups"] == ["Quants"]  # a reported name stays hidden
        assert (b["items"], b["coins_spent"], b["badges"], b["friends"]) == (0, 0, 0, 1)

    def test_the_totals_count_this_weeks_newcomers_and_players(self, db):
        ann, ben, cat = (uid(db, name) for name in ("Ann", "Ben", "Cat"))
        game(db, (ann, "Ann", 1, 0, 1), (ben, "Ben", 2, 0, 1))
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
        db.conn.execute("UPDATE users SET created_at = ? WHERE id IN (?, ?)", (old, ann, cat))
        totals = players.report(db, full=False)["summary"]
        assert (totals["accounts"], totals["new_recently"], totals["played_recently"], totals["played_ever"]) == (3, 1, 2, 2)
        assert totals["games"] == 1 and totals["coins"] == sum(db._fetch_user(u)["coins"] for u in (ann, ben, cat))
        later = players.report(db, full=False, now=datetime.now(timezone.utc) + timedelta(days=8))["summary"]
        assert (later["new_recently"], later["played_recently"], later["played_ever"]) == (0, 0, 2)

    def test_only_the_full_report_carries_emails_and_accuracy_flags(self, db):
        ann = uid(db, "Ann")
        db.conn.execute(
            "INSERT INTO accuracy_flags (user_id, status, quotes, bullseyes, baseline, p_value, after_quote_id, "
            "last_quote_id, created_at, updated_at) VALUES (?, 'open', 30, 20, 0.05, 0.0001, 0, 0, 'now', 'now')",
            (ann,),
        )
        team_view = row(players.report(db, full=False), "Ann")
        assert "email" not in team_view and "flag" not in team_view
        admin_view = row(players.report(db, full=True), "Ann")
        assert (admin_view["email"], admin_view["flag"]) == ("ann@example.com", "open")


class TestTheExcelFile:
    def sheet(self, db, full):
        data = players.report(db, full=full)
        return load_workbook(io.BytesIO(players.workbook(data, site="https://almanac.test", exported_by="Ryan")))

    def test_it_has_a_row_per_player_with_real_numbers_and_dates(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        game(db, (ann, "Ann", 1, 1, 5), (ben, "Ben", 2, 0, 2))
        book = self.sheet(db, full=True)
        sheet = book["Players"]
        headings = [cell.value for cell in sheet[1]]
        assert headings[:5] == ["Player", "Handle", "Email", "Joined", "Last played"] and "Accuracy flag" in headings
        first = dict(zip(headings, [cell.value for cell in sheet[2]]))
        assert (first["Player"], first["Email"], first["Games"], first["Wins"], first["Win rate"]) == ("Ann", "ann@example.com", 1, 1, 1)
        assert first["Joined"].date() == datetime.now(timezone.utc).date() and first["Prestige"] == db._fetch_user(ann)["prestige"]
        assert first["Profile"] == f"https://almanac.test/u/{db._fetch_user(ann)['public_id']}"
        assert sheet.freeze_panes == "B2" and sheet.auto_filter.ref.startswith("A1:")
        assert sheet.max_row == 3
        summary = {r[0].value: r[1].value for r in book["Summary"].iter_rows() if r[0].value}
        assert (summary["Accounts"], summary["Games saved (hosted and live)"], summary["Exported by"]) == (2, 1, "Ryan")

    def test_a_teammates_file_leaves_out_emails_and_flags(self, db):
        uid(db, "Ann")
        headings = [cell.value for cell in self.sheet(db, full=False)["Players"][1]]
        assert "Email" not in headings and "Accuracy flag" not in headings and headings[0] == "Player"

    def test_a_name_that_looks_like_a_formula_stays_text(self, db):
        user, _ = db.sign_in_google("g-x", "x@example.com", '=HYPERLINK("http://evil.example","Ann")')
        social.set_handle(db, user["id"], "sneaky")
        cell = self.sheet(db, full=True)["Players"]["A2"]
        assert cell.data_type == "s" and cell.value.startswith("=HYPERLINK")

    def test_an_empty_site_still_makes_a_file(self, db):
        assert self.sheet(db, full=True)["Players"].max_row == 1


class TestWhoMaySee:
    def test_only_admins_and_the_team_get_the_page(self, app_db, monkeypatch):
        monkeypatch.setenv("ADMIN_EMAILS", "ann@example.com")
        ann, ben, anon = client_for("Ann"), client_for("Ben"), TestClient(app_module.app)
        for path in ("/api/admin/players", "/api/admin/players.xlsx", "/api/admin/team"):
            assert anon.get(path).status_code == 401
            assert ben.get(path).status_code == 403
        answer = ann.get("/api/admin/players")
        assert answer.status_code == 200 and answer.headers["cache-control"] == "no-store"
        body = answer.json()
        assert body["viewer"] == {"admin": True} and body["summary"]["accounts"] == 2
        assert {p["email"] for p in body["players"]} == {"ann@example.com", "ben@example.com"}
        assert (ann.get("/api/me").json()["user"]["team"], ben.get("/api/me").json()["user"]["team"]) == (True, False)
        assert anon.get("/api/me").json() == {"user": None}

    def test_an_admin_adds_a_teammate_who_can_look_but_not_touch(self, app_db, monkeypatch):
        monkeypatch.setenv("ADMIN_EMAILS", "ann@example.com")
        ann, ben = client_for("Ann"), client_for("Ben")
        added = ann.post("/api/admin/team", json={"email": "  Ben@Example.com "}).json()["team"]
        assert [(t["email"], t["added_by"], t["account"]) for t in added] == [("ben@example.com", "Ann", "Ben")]
        me = ben.get("/api/me").json()["user"]
        assert (me["admin"], me["team"]) == (False, True)
        body = ben.get("/api/admin/players").json()
        assert body["viewer"] == {"admin": False} and len(body["players"]) == 2
        assert all("email" not in p and "flag" not in p for p in body["players"])
        # A teammate can download the table, without the admins' columns, and nothing else.
        file = ben.get("/api/admin/players.xlsx")
        assert file.status_code == 200 and "almanac-players-" in file.headers["content-disposition"]
        assert "Email" not in [c.value for c in load_workbook(io.BytesIO(file.content))["Players"][1]]
        assert ben.get("/api/admin/team").status_code == 403
        assert ben.post("/api/admin/team", json={"email": "cat@example.com"}).status_code == 403
        assert ben.delete("/api/admin/team/ben@example.com").status_code == 403
        assert ben.get("/api/admin/flags").status_code == 403 and ben.get("/api/admin/reports").status_code == 403
        # Taken off the list, the page closes again.
        assert ann.delete("/api/admin/team/BEN@example.com").json()["team"] == []
        assert ben.get("/api/admin/players").status_code == 403

    def test_the_team_list_takes_emails_only_and_someone_who_has_not_signed_in_yet(self, app_db, monkeypatch):
        monkeypatch.setenv("ADMIN_EMAILS", "ann@example.com")
        ann = client_for("Ann")
        for bad in ("cat", "cat@", "a b@example.com", "@example.com"):
            assert ann.post("/api/admin/team", json={"email": bad}).status_code == 400
        ann.post("/api/admin/team", json={"email": "cat@example.com"})
        ann.post("/api/admin/team", json={"email": "cat@example.com"})  # twice is once
        listed = ann.get("/api/admin/team").json()
        assert [(t["email"], t["account"]) for t in listed["team"]] == [("cat@example.com", None)]
        assert listed["admins"] == ["ann@example.com"]
        cat = client_for("Cat")  # signs in for the first time, already on the list
        assert cat.get("/api/admin/players").status_code == 200
        assert ann.get("/api/admin/team").json()["team"][0]["account"] == "Cat"

    def test_the_admins_file_downloads_with_every_column(self, app_db, monkeypatch):
        monkeypatch.setenv("ADMIN_EMAILS", "ann@example.com")
        ann = client_for("Ann")
        file = ann.get("/api/admin/players.xlsx")
        assert file.status_code == 200 and file.headers["content-type"] == players.XLSX
        assert file.headers["cache-control"] == "no-store"
        headings = [c.value for c in load_workbook(io.BytesIO(file.content))["Players"][1]]
        assert len(headings) == len(players.COLUMNS) and "Email" in headings
