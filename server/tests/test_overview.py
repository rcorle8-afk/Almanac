"""The overview page (Ryan, Nov 17, 2026): the app's structure, plans, services and live status
for the team. Most of these tests keep the written-out structure honest against the code."""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import app as app_module
from server import overview
from server.db import Database
from server.tests.test_rooms import receive_until
from server.tests.test_social import app_db, client_for, fake_verify  # noqa: F401  (fixtures)

SERVER = Path(overview.__file__).resolve().parent
CLIENT_MAIN = SERVER.parent / "client" / "src" / "main.tsx"


class TestTheStructureMatchesTheCode:
    def test_every_server_module_is_described_and_every_description_has_a_module(self):
        rows = overview.modules()
        assert [row["name"] for row in rows if not row["about"]] == []  # a new file needs a line in MODULES
        assert [row["name"] for row in rows if row["lines"] is None] == []  # and a removed one loses its line
        assert all(row["lines"] > 0 for row in rows)

    def test_every_table_is_described_and_every_description_has_a_table(self, tmp_path):
        db = Database(tmp_path / "tables.db")
        rows = overview.tables(db.conn)
        assert [row["name"] for row in rows if not row["about"]] == []  # a new table needs a line in TABLES
        assert {row["name"] for row in rows} == set(overview.TABLES)
        assert [row["name"] for row in rows][:2] == ["users", "sessions"]  # in TABLES' order, not the alphabet's

    def test_every_page_the_client_routes_is_listed(self):
        source = CLIENT_MAIN.read_text(encoding="utf-8")
        bare = lambda path: path.rstrip("/") or "/"  # "/u/" and "/u" are one page
        routed = {bare(path) for path in re.findall(r'at\("(/[^"]*)"\)', source)}
        listed = {bare(page["path"]) for page in overview.PAGES}
        assert routed - listed - set(overview.PAGE_ALIASES) == set()
        assert listed - routed - {"/"} == set()
        assert set(overview.PAGE_ALIASES.values()) <= listed
        assert {page["access"] for page in overview.PAGES} <= {"everyone", "signed_in", "team", "admin"}

    def test_the_layers_name_real_files(self):
        app_layer = next(layer for layer in overview.LAYERS if layer["id"] == "app")
        for part in app_layer["parts"]:
            if part["name"] == "Client":
                continue
            for name in part["where"].split(", "):
                assert (SERVER / name).exists(), f"{part['name']} names {name}"
        named = {name for part in app_layer["parts"] for name in part["where"].split(", ")}
        assert {"rooms.py", "engine/", "db.py", "social.py", "live.py", "players.py", "overview.py"} <= named

    def test_outside_services_come_from_the_data_file(self):
        filled = overview.layers([{"service": "Fly.io", "category": "Hosting", "role": "Runs the server."}])
        services = next(layer for layer in filled if layer["id"] == "services")
        assert services["parts"] == [{"name": "Fly.io", "about": "Runs the server.", "where": "Runs the app"}]
        assert next(layer for layer in overview.LAYERS if layer["id"] == "services")["parts"] == []  # the original is untouched


class TestThePlansFile:
    def test_it_ships_with_the_server_and_has_what_the_page_reads(self):
        data = json.loads(overview.DATA.read_text(encoding="utf-8"))
        for key in ("refreshed_at", "principles", "goals", "milestones", "timeline", "services", "costs", "cost_summary", "stack", "snapshot"):
            assert key in data, key
        assert len(data["goals"]) > 30 and {"section", "goal", "status", "note"} <= set(data["goals"][0])
        assert {m["id"] for m in data["milestones"]} >= {"M0", "M6"}
        assert "production" not in data and "accounts" not in data["snapshot"][0]  # the server counts its own

    def test_nothing_in_it_looks_like_a_key(self):
        text = overview.DATA.read_text(encoding="utf-8")
        for pattern in (r"sk-ant-", r"GOCSPX-", r"-----BEGIN", r"AIza[0-9A-Za-z_-]{20}", r"FlyV1 "):
            assert not re.search(pattern, text), pattern


class TestThePage:
    def test_only_admins_and_the_team_get_it(self, app_db, monkeypatch):
        monkeypatch.setenv("ADMIN_EMAILS", "ann@example.com")
        ann, ben, anon = client_for("Ann"), client_for("Ben"), TestClient(app_module.app)
        assert anon.get("/api/admin/overview").status_code == 401
        assert ben.get("/api/admin/overview").status_code == 403
        answer = ann.get("/api/admin/overview")
        assert answer.status_code == 200 and answer.headers["cache-control"] == "no-store"
        body = answer.json()
        assert body["viewer"] == {"admin": True}
        assert [layer["id"] for layer in body["layers"]] == ["screens", "app", "data", "services", "offline"]
        assert len(body["pages"]) == len(overview.PAGES) and len(body["modules"]) == len(overview.MODULES)
        assert body["goals"] and body["milestones"] and body["services"] and body["stack"] and body["timeline"]
        assert next(layer for layer in body["layers"] if layer["id"] == "services")["parts"]
        assert body["cost_summary"]["monthly_max_usd"] > 0 and body["project"]["tests"] > 0

    def test_the_status_is_read_from_the_running_server(self, app_db, monkeypatch):
        monkeypatch.setenv("ADMIN_EMAILS", "ann@example.com")
        ann = client_for("Ann")
        client_for("Ben")
        before = ann.get("/api/admin/overview").json()
        status = before["status"]
        assert (status["accounts"], status["rooms"], status["people_at_tables"], status["admins"]) == (2, 0, 0, 1)
        assert status["questions_playable"] == len(app_module.hub.questions) and status["questions_in_bank"] >= 400
        assert status["uptime_seconds"] >= 0 and status["started_at"].startswith("20") and status["database_bytes"] > 0
        assert [switch["name"] for switch in status["switches"]] == [
            "Sign in with Google", "Phone notifications", "Nightly live game", "Dev sign-in", "Unverified questions",
        ]
        assert all(isinstance(switch["on"], bool) for switch in status["switches"])
        users = next(table for table in before["tables"] if table["name"] == "users")
        assert users["rows"] == 2 and users["about"]
        with TestClient(app_module.app).websocket_connect("/ws") as host, TestClient(app_module.app).websocket_connect("/ws") as phone:
            host.send_json({"type": "host_create", "config": {}})
            code = receive_until(host, lambda m: m["type"] == "hosted")["room_code"]
            phone.send_json({"type": "join", "room_code": code, "name": "Gus"})
            receive_until(phone, lambda m: m["type"] == "joined")
            during = ann.get("/api/admin/overview").json()["status"]
            assert (during["rooms"], during["rooms_in_play"], during["people_at_tables"]) == (1, 0, 1)

    def test_a_teammate_sees_the_team_by_name_and_an_admin_by_email(self, app_db, monkeypatch):
        monkeypatch.setenv("ADMIN_EMAILS", "ann@example.com, owner-who-never-signed-in@example.com")
        ann, ben = client_for("Ann"), client_for("Ben")
        ann.post("/api/admin/team", json={"email": "ben@example.com"})
        ann.post("/api/admin/team", json={"email": "not-here-yet@example.com"})
        admin_view = ann.get("/api/admin/overview").json()["team"]
        assert admin_view["admins"] == [
            {"name": "Ann", "email": "ann@example.com"},
            {"name": None, "email": "owner-who-never-signed-in@example.com"},
        ]
        assert [mate["email"] for mate in admin_view["teammates"]] == ["ben@example.com", "not-here-yet@example.com"]
        body = ben.get("/api/admin/overview").json()
        assert body["viewer"] == {"admin": False}
        assert body["team"] == {
            "admins": [{"name": "Ann"}],
            "teammates": [{"name": "Ben"}],
            "admin_count": 2,
            "teammate_count": 2,
        }
        assert "example.com" not in json.dumps(body["team"])
