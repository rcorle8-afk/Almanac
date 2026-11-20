"""Groups since Nov 11, 2026: the 1,500-coin charge to start one, the invite link, the bio, the
icon (a drawing and colour, or an uploaded picture), and reports on the bio and the picture."""

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from server import app as app_module
from server import images, social
from server.db import Database
from server.tests.test_social import account, app_db, client_for, fake_verify, uid  # noqa: F401  (fixtures)

GROUP_ICON = Path(__file__).resolve().parents[2] / "client" / "src" / "components" / "GroupIcon.tsx"
BUILT = (app_module.CLIENT_DIST / "index.html").is_file()


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "groups.db")


def coins(db, user_id):
    return db._fetch_user(user_id)["coins"]


def set_coins(db, user_id, amount):
    db.conn.execute("UPDATE users SET coins = ? WHERE id = ?", (amount, user_id))


def picture(size=(40, 30), color=(200, 30, 30), kind="PNG", **options) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, color).save(out, kind, **options)
    return out.getvalue()


def code_of(db, owner, group):
    return social.group_detail(db, owner, group)["invite_code"]


class TestCost:
    def test_starting_a_group_takes_the_coins(self, db):
        ann = uid(db, "Ann")
        set_coins(db, ann, social.GROUP_COST + 40)
        group = social.create_group(db, ann, "Quants")
        assert coins(db, ann) == 40 and group["role"] == "owner"

    def test_too_few_coins_starts_nothing_and_costs_nothing(self, db):
        ann = uid(db, "Ann")
        set_coins(db, ann, social.GROUP_COST - 1)
        with pytest.raises(social.SocialError, match="You need 1 more") as refused:
            social.create_group(db, ann, "Quants")
        assert refused.value.status == 402
        assert coins(db, ann) == social.GROUP_COST - 1 and social.my_groups(db, ann) == []

    def test_a_new_account_cannot_afford_one(self, db):
        user, _ = db.sign_in_google("g-new", "new@example.com", "New")  # holds the welcome coins only
        with pytest.raises(social.SocialError, match="costs 1,500 coins"):
            social.create_group(db, user["id"], "Quants")

    def test_a_refused_name_or_a_full_set_costs_nothing(self, db, monkeypatch):
        ann = uid(db, "Ann")
        before = coins(db, ann)
        with pytest.raises(ValueError):
            social.create_group(db, ann, "x")
        assert coins(db, ann) == before
        monkeypatch.setattr(social, "MAX_GROUPS_OWNED", 1)
        social.create_group(db, ann, "Quants")
        with pytest.raises(social.SocialError, match="up to 1"):
            social.create_group(db, ann, "Second")
        assert coins(db, ann) == before - social.GROUP_COST

    def test_disbanding_gives_nothing_back(self, db):
        ann = uid(db, "Ann")
        before = coins(db, ann)
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.disband(db, ann, group)
        assert coins(db, ann) == before - social.GROUP_COST

    def test_the_social_page_is_told_the_price_and_the_balance(self, db):
        ann = uid(db, "Ann")
        set_coins(db, ann, 2000)
        view = social.overview(db, ann)
        assert (view["coins"], view["group_cost"], view["groups_left"]) == (2000, 1500, social.MAX_GROUPS_OWNED)
        social.create_group(db, ann, "Quants")
        view = social.overview(db, ann)
        assert (view["coins"], view["groups_left"]) == (500, social.MAX_GROUPS_OWNED - 1)


class TestStartedWithEverything:
    def test_a_group_can_be_started_with_its_bio_and_icon(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants", "  Thursdays   at 7. ", "owl", "forest")
        assert group["icon"] == {"glyph": "owl", "color": "forest", "image": None}
        assert social.group_detail(db, ben, group["public_id"])["bio"] == "Thursdays at 7."

    @pytest.mark.parametrize(
        "extras",
        [{"bio": "what the fuck"}, {"bio": "x" * 161}, {"glyph": "skull"}, {"color": "red"}],
        ids=["rude-bio", "long-bio", "unknown-icon", "unknown-colour"],
    )
    def test_a_bad_bio_or_icon_starts_nothing_and_costs_nothing(self, db, extras):
        ann = uid(db, "Ann")
        before = coins(db, ann)
        with pytest.raises(ValueError):
            social.create_group(db, ann, "Quants", **extras)
        assert coins(db, ann) == before and social.my_groups(db, ann) == []

    def test_over_http(self, app_db):
        ann = client_for("Ann")
        made = ann.post("/api/groups", json={"name": "Quants", "bio": "Thursdays at 7.", "glyph": "lighthouse", "color": "navy"}).json()
        assert made["icon"]["glyph"] == "lighthouse" and made["icon"]["color"] == "navy"
        assert ann.get(f"/api/groups/{made['public_id']}").json()["bio"] == "Thursdays at 7."
        assert ann.post("/api/groups", json={"name": "Second", "glyph": "skull"}).status_code == 400


class TestPrestige:
    def test_a_groups_prestige_is_its_members_added_up(self, db):
        ann, ben, cat = uid(db, "Ann"), uid(db, "Ben"), uid(db, "Cat")
        for user, prestige in ((ann, 300), (ben, 450), (cat, 50)):
            db.conn.execute("UPDATE users SET prestige = ? WHERE id = ?", (prestige, user))
        group = social.create_group(db, ann, "Quants")
        assert group["prestige"] == 300
        social.join(db, ben, group["public_id"], via_room=True)
        social.join(db, cat, group["public_id"], via_room=True)
        assert social.my_groups(db, ann)[0]["prestige"] == 800
        assert social.group_detail(db, cat, group["public_id"])["prestige"] == 800
        assert social.overview(db, ben)["groups"][0]["prestige"] == 800
        social.leave(db, cat, group["public_id"])
        assert social.my_groups(db, ann)[0]["prestige"] == 750

    def test_it_follows_a_members_wins(self, db):
        ann = uid(db, "Ann")
        group = social.create_group(db, ann, "Quants")["public_id"]
        db.conn.execute("UPDATE users SET prestige = prestige + 100 WHERE id = ?", (ann,))
        assert social.group_preview(db, group, code_of(db, ann, group))["prestige"] == 100


class TestInviteLink:
    def test_members_see_the_link_and_outsiders_dont(self, db):
        ann, ben, cat = uid(db, "Ann"), uid(db, "Ben"), uid(db, "Cat")
        group = social.create_group(db, ann, "Quants")["public_id"]
        code = code_of(db, ann, group)
        assert len(code) >= 12
        assert social.group_detail(db, cat, group)["invite_code"] is None
        social.join(db, ben, group, code=code)
        assert social.group_detail(db, ben, group)["invite_code"] == code

    def test_the_link_lets_anyone_join_and_the_owner_hears(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        code = code_of(db, ann, group)
        seen = social.group_detail(db, ben, group, code)
        assert seen["invited"] and seen["by_link"] and seen["role"] is None
        assert social.join(db, ben, group, code=code)["role"] == "member"
        heard = social.notifications(db, ann)["items"][0]
        assert (heard["kind"], heard["actor"]["name"]) == ("group_joined", "Ben")

    @pytest.mark.parametrize("code", ["", "nope", None])
    def test_a_wrong_code_opens_nothing(self, db, code):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        assert social.group_detail(db, ben, group, code)["invited"] is False
        with pytest.raises(social.SocialError, match="no longer open"):
            social.join(db, ben, group, code=code)
        with pytest.raises(social.SocialError, match="no longer open"):
            social.group_preview(db, group, code)

    def test_a_new_link_kills_the_old_one_and_only_the_owner_can_make_it(self, db):
        ann, ben, cat = uid(db, "Ann"), uid(db, "Ben"), uid(db, "Cat")
        group = social.create_group(db, ann, "Quants")["public_id"]
        old = code_of(db, ann, group)
        social.join(db, ben, group, code=old)
        with pytest.raises(social.SocialError, match="owner"):
            social.reset_invite_link(db, ben, group)
        new = social.reset_invite_link(db, ann, group)
        assert new != old and code_of(db, ben, group) == new
        with pytest.raises(social.SocialError, match="no longer open"):
            social.join(db, cat, group, code=old)
        assert social.join(db, cat, group, code=new)["role"] == "member"

    def test_someone_the_owner_blocked_cannot_use_it(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        code = code_of(db, ann, group)
        social.block(db, ann, ben)
        assert social.group_detail(db, ben, group, code)["invited"] is False
        with pytest.raises(social.SocialError, match="no longer open"):
            social.join(db, ben, group, code=code)

    def test_a_full_group_takes_nobody_by_link(self, db, monkeypatch):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        monkeypatch.setattr(social, "MAX_GROUP_MEMBERS", 1)
        with pytest.raises(social.SocialError, match="full"):
            social.join(db, ben, group, code=code_of(db, ann, group))

    def test_the_preview_shows_the_group_to_someone_not_signed_in(self, db):
        ann = uid(db, "Ann")
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.set_bio(db, ann, group, "Thursdays at 7.")
        seen = social.group_preview(db, group, code_of(db, ann, group))
        assert (seen["name"], seen["bio"], seen["member_count"], seen["role"]) == ("Quants", "Thursdays at 7.", 1, None)
        assert seen["owner"]["name"] == "Ann" and set(seen["owner"]) == {"name", "avatar"}
        assert seen["icon"] == {"glyph": "letters", "color": "blue", "image": None}

    def test_groups_from_before_the_link_get_one_at_startup(self, tmp_path):
        path = tmp_path / "old.db"
        db = Database(path)
        ann = uid(db, "Ann")
        group = social.create_group(db, ann, "Quants")["public_id"]
        db.conn.execute("UPDATE groups SET invite_code = NULL")
        reopened = Database(path)
        assert code_of(reopened, ann, group)


class TestBioAndIcon:
    def test_the_owner_writes_the_bio_under_the_usual_rules(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        assert social.set_bio(db, ann, group, "  Thursdays   at 7.  ") == "Thursdays at 7."
        assert social.group_detail(db, ben, group)["bio"] == "Thursdays at 7."
        for bad in ("x" * 161, "what the fuck"):
            with pytest.raises(ValueError):
                social.set_bio(db, ann, group, bad)
        with pytest.raises(social.SocialError, match="owner"):
            social.set_bio(db, ben, group, "Mine now")

    def test_the_icon_starts_as_initials_and_takes_only_the_listed_choices(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        assert social.my_groups(db, ann)[0]["icon"] == {"glyph": "letters", "color": "blue", "image": None}
        assert social.set_icon(db, ann, group, "rocket", None)["glyph"] == "rocket"
        assert social.set_icon(db, ann, group, None, "forest") == {"glyph": "rocket", "color": "forest", "image": None}
        with pytest.raises(social.SocialError, match="icon"):
            social.set_icon(db, ann, group, "skull", None)
        with pytest.raises(social.SocialError, match="colour"):
            social.set_icon(db, ann, group, None, "red")
        with pytest.raises(social.SocialError, match="owner"):
            social.set_icon(db, ben, group, "book", None)

    @pytest.mark.skipif(not GROUP_ICON.exists(), reason="client icon not written yet")
    def test_the_client_can_draw_every_icon_and_colour(self):
        source = GROUP_ICON.read_text(encoding="utf-8")
        missing = [name for name in (*social.GROUP_GLYPHS, *social.GROUP_COLORS) if f"{name}:" not in source]
        assert missing == []


class TestPicture:
    def test_an_upload_is_stored_as_a_small_square(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        icon = social.set_image(db, ann, group, picture(size=(900, 300)))
        assert icon["image"].startswith(f"/api/groups/{group}/image?v=")
        stored = Image.open(BytesIO(social.group_image(db, group, ben)))
        assert (stored.format, stored.size) == ("WEBP", (images.ICON_SIDE, images.ICON_SIDE))
        assert social.my_groups(db, ann)[0]["icon"]["image"] == icon["image"]

    def test_a_new_upload_gets_a_new_address_and_removing_goes_back_to_the_drawing(self, db):
        ann = uid(db, "Ann")
        group = social.create_group(db, ann, "Quants")["public_id"]
        first = social.set_image(db, ann, group, picture())["image"]
        second = social.set_image(db, ann, group, picture(color=(0, 0, 200)))["image"]
        assert first != second
        assert social.remove_image(db, ann, group) == {"glyph": "letters", "color": "blue", "image": None}
        with pytest.raises(social.SocialError):
            social.group_image(db, group, ann)

    def test_nothing_of_the_original_file_survives(self, db):
        ann = uid(db, "Ann")
        group = social.create_group(db, ann, "Quants")["public_id"]
        marked = Image.Exif()
        marked[0x010E] = "taken at home, 39.1653 N 86.5264 W"  # ImageDescription
        social.set_image(db, ann, group, picture(kind="JPEG", exif=marked) + b"hidden after the picture")
        stored = social.group_image(db, group, ann)
        assert b"39.1653" not in stored and b"hidden after" not in stored
        assert not Image.open(BytesIO(stored)).getexif()

    @pytest.mark.parametrize(
        "upload",
        [
            b"",
            b"not a picture at all",
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            picture(kind="GIF"),
            picture(size=(images.MAX_SIDE + 1, 10)),
            picture()[:60],
        ],
        ids=["empty", "text", "svg", "gif", "too-wide", "cut-short"],
    )
    def test_what_isnt_a_picture_we_take_is_refused(self, db, upload):
        ann = uid(db, "Ann")
        group = social.create_group(db, ann, "Quants")["public_id"]
        with pytest.raises(ValueError):
            social.set_image(db, ann, group, upload)
        assert social.my_groups(db, ann)[0]["icon"]["image"] is None

    def test_too_many_bytes_are_refused_before_decoding(self):
        with pytest.raises(ValueError, match="too big"):
            images.square_icon(b"x" * (images.UPLOAD_LIMIT + 1))

    def test_only_the_owner_uploads_or_removes(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.join(db, ben, group, via_room=True)
        for action in (lambda: social.set_image(db, ben, group, picture()), lambda: social.remove_image(db, ben, group)):
            with pytest.raises(social.SocialError, match="owner"):
                action()

    def test_disbanding_takes_the_picture_with_it(self, db):
        ann = uid(db, "Ann")
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.set_image(db, ann, group, picture())
        social.disband(db, ann, group)
        assert db.conn.execute("SELECT COUNT(*) FROM group_images").fetchone()[0] == 0


class TestReports:
    def test_a_reported_bio_hides_from_everyone_but_the_owner(self, db):
        ann, ben, cat = uid(db, "Ann"), uid(db, "Ben"), uid(db, "Cat")
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.set_bio(db, ann, group, "Something rude")
        social.report(db, ben, "group_bio", group)
        assert social.group_detail(db, cat, group)["bio"] == ""
        mine = social.group_detail(db, ann, group)
        assert mine["bio"] == "Something rude" and mine["bio_hidden"] is True
        [queued] = social.open_reports(db)
        assert (queued["kind"], queued["text"], queued["group"]["name"]) == ("group_bio", "Something rude", "Quants")
        social.resolve(db, queued["id"], "clear")
        assert social.group_detail(db, ann, group)["bio"] == "" and social.open_reports(db) == []

    def test_an_edit_does_not_unhide_a_reported_bio_but_emptying_it_settles_it(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.set_bio(db, ann, group, "Something rude")
        social.report(db, ben, "group_bio", group)
        social.set_bio(db, ann, group, "Something rude again")
        assert social.group_detail(db, ben, group)["bio"] == ""
        social.set_bio(db, ann, group, "")
        assert social.open_reports(db) == [] and social.group_detail(db, ann, group)["bio_hidden"] is False

    def test_a_reported_picture_shows_only_to_its_owner_and_the_reviewer(self, db):
        ann, ben, cat = uid(db, "Ann"), uid(db, "Ben"), uid(db, "Cat")
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.set_icon(db, ann, group, "rocket", "forest")
        social.set_image(db, ann, group, picture())
        social.report(db, ben, "group_image", group)
        assert social.group_detail(db, cat, group)["icon"] == {"glyph": "rocket", "color": "forest", "image": None}
        for outsider in (cat, None):
            with pytest.raises(social.SocialError):
                social.group_image(db, group, outsider)
        mine = social.group_detail(db, ann, group)
        assert mine["icon"]["image"] and mine["image_hidden"] is True
        assert social.group_image(db, group, ann) and social.group_image(db, group, cat, reviewing=True)
        [queued] = social.open_reports(db)
        assert queued["kind"] == "group_image" and queued["image"] == mine["icon"]["image"]

    def test_swapping_a_reported_picture_keeps_it_hidden_until_reviewed(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.set_image(db, ann, group, picture())
        social.report(db, ben, "group_image", group)
        social.set_image(db, ann, group, picture(color=(0, 0, 200)))
        assert social.group_detail(db, ben, group)["icon"]["image"] is None
        [queued] = social.open_reports(db)
        social.resolve(db, queued["id"], "restore")
        assert social.group_detail(db, ben, group)["icon"]["image"]

    def test_clearing_a_picture_report_takes_the_picture_down(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.set_image(db, ann, group, picture())
        social.report(db, ben, "group_image", group)
        [queued] = social.open_reports(db)
        social.resolve(db, queued["id"], "clear")
        mine = social.group_detail(db, ann, group)
        assert mine["icon"]["image"] is None and mine["image_hidden"] is False
        assert db.conn.execute("SELECT COUNT(*) FROM group_images").fetchone()[0] == 0

    def test_removing_a_reported_picture_closes_its_reports(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        social.set_image(db, ann, group, picture())
        social.report(db, ben, "group_image", group)
        social.remove_image(db, ann, group)
        assert social.open_reports(db) == []

    def test_there_must_be_something_to_report(self, db):
        ann, ben = uid(db, "Ann"), uid(db, "Ben")
        group = social.create_group(db, ann, "Quants")["public_id"]
        for kind in ("group_bio", "group_image"):
            with pytest.raises(social.SocialError, match="nothing"):
                social.report(db, ben, kind, group)
        social.set_bio(db, ann, group, "Hi")
        with pytest.raises(social.SocialError, match="own"):
            social.report(db, ann, "group_bio", group)


class TestApi:
    def test_a_poor_account_is_told_what_it_costs(self, app_db):
        ann = client_for("Ann", coins=750)
        refused = ann.post("/api/groups", json={"name": "Quants"})
        assert refused.status_code == 402 and "750 more" in refused.json()["detail"]
        assert ann.get("/api/me").json()["user"]["coins"] == 750

    def test_customizing_over_http(self, app_db):
        ann, ben = client_for("Ann"), client_for("Ben")
        group = ann.post("/api/groups", json={"name": "Quants"}).json()["public_id"]
        changed = ann.patch(f"/api/groups/{group}", json={"bio": "Thursdays at 7.", "glyph": "bolt", "color": "purple"}).json()
        assert (changed["bio"], changed["icon"]["glyph"], changed["icon"]["color"], changed["name"]) == ("Thursdays at 7.", "bolt", "purple", "Quants")
        assert ann.patch(f"/api/groups/{group}", json={"glyph": "skull"}).status_code == 400
        assert ann.patch(f"/api/groups/{group}", json={"bio": "x" * 200}).status_code == 400
        assert ben.patch(f"/api/groups/{group}", json={"bio": "Mine"}).status_code == 403

    def test_a_picture_goes_up_is_served_and_comes_down(self, app_db):
        ann, ben = client_for("Ann"), client_for("Ben")
        group = ann.post("/api/groups", json={"name": "Quants"}).json()["public_id"]
        assert ben.put(f"/api/groups/{group}/image", content=picture()).status_code == 403
        assert ann.put(f"/api/groups/{group}/image", content=b"nope").status_code == 400
        assert ann.put(f"/api/groups/{group}/image", content=b"x" * (images.UPLOAD_LIMIT + 1)).status_code == 413
        icon = ann.put(f"/api/groups/{group}/image", content=picture(), headers={"Content-Type": "image/png"}).json()["icon"]
        served = TestClient(app_module.app).get(icon["image"])  # no sign-in: the address is enough
        assert served.status_code == 200 and served.headers["content-type"] == "image/webp"
        assert served.headers["cache-control"].startswith("private")
        assert ann.delete(f"/api/groups/{group}/image").json()["icon"]["image"] is None
        assert ann.get(icon["image"]).status_code == 404

    def test_a_reported_picture_is_served_only_to_the_owner_and_an_admin(self, app_db, monkeypatch):
        ann, ben, cat = client_for("Ann"), client_for("Ben"), client_for("Cat")
        group = ann.post("/api/groups", json={"name": "Quants"}).json()["public_id"]
        address = ann.put(f"/api/groups/{group}/image", content=picture()).json()["icon"]["image"]
        assert ben.post("/api/reports", json={"kind": "group_image", "public_id": group}).json() == {"ok": True}
        assert ann.get(address).status_code == 200
        assert ben.get(address).status_code == 404 and TestClient(app_module.app).get(address).status_code == 404
        monkeypatch.setenv("ADMIN_EMAILS", "cat@example.com")
        [queued] = cat.get("/api/admin/reports").json()["reports"]
        assert queued["image"] == address and cat.get(address).status_code == 200

    def test_an_invite_link_end_to_end(self, app_db):
        ann, ben, anon = client_for("Ann"), client_for("Ben"), TestClient(app_module.app)
        group = ann.post("/api/groups", json={"name": "Quants"}).json()["public_id"]
        code = ann.get(f"/api/groups/{group}").json()["invite_code"]
        seen = anon.get(f"/api/groups/{group}/preview", params={"invite": code}).json()
        assert seen["name"] == "Quants" and seen["owner"]["name"] == "Ann"
        assert anon.get(f"/api/groups/{group}/preview", params={"invite": "nope"}).status_code == 404
        assert anon.get(f"/api/groups/{group}").status_code == 401
        assert ben.get(f"/api/groups/{group}", params={"invite": code}).json()["by_link"] is True
        assert ben.post(f"/api/groups/{group}/join", json={"invite": "nope"}).status_code == 404
        assert ben.post(f"/api/groups/{group}/join", json={"invite": code}).json()["role"] == "member"
        assert ben.post(f"/api/groups/{group}/invite-link").status_code == 403
        fresh = ann.post(f"/api/groups/{group}/invite-link").json()["invite_code"]
        assert fresh != code and anon.get(f"/api/groups/{group}/preview", params={"invite": code}).status_code == 404

    @pytest.mark.skipif(not BUILT, reason="client not built")
    def test_a_shared_link_previews_with_the_groups_name_and_escapes_it(self, app_db):
        ann, anon = client_for("Ann"), TestClient(app_module.app)
        group = ann.post("/api/groups", json={"name": 'Quants "<b>" & Co'}).json()["public_id"]
        ann.patch(f"/api/groups/{group}", json={"bio": "Thursdays at 7 <script>"})
        code = ann.get(f"/api/groups/{group}").json()["invite_code"]
        page = anon.get(f"/g/{group}", params={"invite": code})
        assert page.headers["cache-control"] == "no-cache"
        assert "<title>Join Quants &quot;&lt;b&gt;&quot; &amp; Co on Almanac</title>" in page.text
        assert 'property="og:description" content="Thursdays at 7 &lt;script&gt;"' in page.text
        assert "<script>" not in page.text.split("</head>")[0].replace('<script type="module"', "")
        assert "/icon-512.png" in page.text and 'id="root"' in page.text
        plain = anon.get(f"/g/{group}", params={"invite": "nope"}).text
        assert "<title>Almanac</title>" in plain and "og:title" not in plain

    @pytest.mark.skipif(not BUILT, reason="client not built")
    def test_a_shared_link_shows_the_groups_picture_unless_its_reported(self, app_db):
        ann, ben, anon = client_for("Ann"), client_for("Ben"), TestClient(app_module.app)
        group = ann.post("/api/groups", json={"name": "Quants"}).json()["public_id"]
        address = ann.put(f"/api/groups/{group}/image", content=picture()).json()["icon"]["image"]
        code = ann.get(f"/api/groups/{group}").json()["invite_code"]
        assert f'content="http://testserver{address.replace("&", "&amp;")}"' in anon.get(f"/g/{group}", params={"invite": code}).text
        ben.post("/api/reports", json={"kind": "group_image", "public_id": group})
        assert "/icon-512.png" in anon.get(f"/g/{group}", params={"invite": code}).text
