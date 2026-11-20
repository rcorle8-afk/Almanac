"""Builds the data behind the Almanac Dashboard (a claude.ai artifact).

    C:/Users/ryanc/.venvs/almanac/Scripts/python tools/dashboard/refresh.py

Reads the project as it stands and writes tools/dashboard/out/almanac-dashboard.json, one file
with a key per dashboard section, then appends today's figures to history.json so the
dashboard can show change over time. Uploading the file to the dashboard is a separate step
that Claude does (see the "Dashboard" note in CLAUDE.md).

What it reads:
- Almanac Development Log.docx: the goals, in order, under their headings. Anything from the
  "Relevant Information" heading on is never read (it holds keys and commands).
- progress.json: each goal's status, the milestones, and the timeline. A goal in the log with no
  entry there shows as "untracked", so a goal you add to the log appears on its own. Its
  `added_goals` are goals set in planning sessions, shown after the log's under their own headings.
- services.json: the outside services and their list prices.
- server/questions/questions.json, verify_runs.jsonl and the verifier's model rates.
- requirements and installed versions, client/package-lock.json, the Dockerfile and fly.toml.
- the test suite (collected, not run) and the source tree's size.
- production usage, only with --production: aggregate counts over Fly SSH, never names or emails.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from importlib import metadata
from pathlib import Path
from xml.etree import ElementTree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from server.questions.validate import SERVABLE_STATUSES  # noqa: E402
from server.questions.verify import DOLLARS_PER_SEARCH, MODELS  # noqa: E402

DEV_LOG = ROOT / "Almanac Development Log.docx"
OUT = HERE / "out" / "almanac-dashboard.json"
HISTORY = HERE / "history.json"
LOG_COPY = HERE / "out" / "dev-log-goals.json"  # the log as last read, for when Word has it open
# What the app's own overview page (/admin/overview, server/overview.py) shows of this: plans,
# services and tool versions. It sits in server/ because that folder is what a deploy ships, so
# run this before deploying, with progress.json already saying what the deploy makes true.
APP_COPY = ROOT / "server" / "overview_data.json"
APP_KEYS = ("refreshed_at", "principles", "goals", "milestones", "timeline", "services", "costs", "cost_summary", "stack")
APP_SNAPSHOT_KEYS = ("date", "goals_done", "goals_total", "milestones_done", "milestones_total", "tests", "code_files", "code_lines")
RUN_LOG = ROOT / "server" / "questions" / "verify_runs.jsonl"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
STOP_HEADING = "relevant information"
STATUS_ORDER = ["done", "in_progress", "ongoing", "planned", "not_started", "untracked"]

SERVER_PACKAGES = [
    ("Server", "fastapi", "Web framework: the HTTP API and the /ws endpoint"),
    ("Server", "starlette", "ASGI toolkit under FastAPI; serves the built client"),
    ("Server", "uvicorn", "ASGI server that runs the app"),
    ("Server", "websockets", "WebSocket protocol for the live game"),
    ("Server", "pydantic", "Validates every message and the question bank"),
    ("Server", "google-auth", "Checks Google sign-in tokens"),
    ("Server", "pywebpush", "Encrypts and sends phone notifications"),
    ("Server", "py-vapid", "Signs push requests with the VAPID key"),
    ("Server", "cryptography", "Key handling for web push"),
    ("Server", "requests", "HTTP client for Google and push services"),
    ("Question tools", "anthropic", "Claude API client for the offline verifier"),
    ("Question tools", "pypdf", "Reads PDF sources the verifier cites"),
    ("Testing", "pytest", "The test suite"),
    ("Testing", "httpx", "HTTP test client"),
]
CLIENT_PACKAGES = {
    "react": ("Client", "UI library"),
    "react-dom": ("Client", "Renders React in the browser"),
    "typescript": ("Client", "Typed JavaScript; checked on every build"),
    "vite": ("Client", "Dev server and production bundler"),
    "@vitejs/plugin-react": ("Client", "React support for Vite"),
    "qrcode": ("Client", "The join QR code on the host lobby"),
    "@fontsource-variable/inter": ("Client", "Inter, bundled (no font service)"),
    "@fontsource-variable/jetbrains-mono": ("Client", "JetBrains Mono for numbers, bundled"),
}


def key(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower().replace("&", " ")).strip().replace("  ", " ")


# The development log.


def read_dev_log(path: Path) -> tuple[list[str], list[dict]]:
    """(principles, goals) from the log. A heading is a paragraph outside a list; a goal is a
    list item, with its depth. A heading with nothing under it is a goal of its own."""
    root = ElementTree.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    principles: list[str] = []
    goals: list[dict] = []
    section = None
    in_goals = False
    parents: dict[int, str] = {}
    for paragraph in root.iter(W + "p"):
        text = "".join(t.text or "" for t in paragraph.iter(W + "t")).strip()
        if not text:
            continue
        level = paragraph.find(f"{W}pPr/{W}numPr/{W}ilvl")
        if level is None:
            lowered = text.lower()
            if lowered.startswith(STOP_HEADING):
                break
            if lowered.startswith("improvements"):
                in_goals = True
                continue
            if not in_goals:
                if lowered != "almanac development log":
                    principles.append(text)
                continue
            if section is not None and not any(g["section"] == section for g in goals):
                goals.append(_goal(section, section, 1, None, len(goals)))
            section = text
            parents = {}
            continue
        if section is None:
            continue
        depth = int(level.get(W + "val")) + 1
        parent = parents.get(depth - 1)
        parents[depth] = text
        goals.append(_goal(section, text, depth, parent, len(goals)))
    if section is not None and not any(g["section"] == section for g in goals):
        goals.append(_goal(section, section, 1, None, len(goals)))
    return principles, goals


def _goal(section: str, text: str, depth: int, parent: str | None, order: int) -> dict:
    return {"section": section, "goal": text, "depth": depth, "parent": parent, "order": order}


def dev_log() -> tuple[list[str], list[dict]]:
    """The log's principles and goals, or what the last refresh read when the log can't be opened.
    Word holds the file while Ryan has it open, which is most of the time he's adding goals, and
    a refresh shouldn't fail for that. The copy holds only what read_dev_log returns, so nothing
    past the stop heading is ever in it."""
    try:
        principles, goals = read_dev_log(DEV_LOG)
    except PermissionError:
        if not LOG_COPY.exists():
            raise
        saved = json.loads(LOG_COPY.read_text(encoding="utf-8"))
        print(f"the development log is open in another program; using its goals as read on {saved['read']}")
        return saved["principles"], saved["goals"]
    LOG_COPY.parent.mkdir(exist_ok=True)
    LOG_COPY.write_text(
        json.dumps({"read": date.today().isoformat(), "principles": principles, "goals": goals}, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    return principles, goals


def added_goals(progress: dict, after: int) -> list[dict]:
    """Goals set in planning sessions rather than written in the log (progress.json's
    `added_goals`), placed after the log's own under their own headings."""
    rows = []
    for index, goal in enumerate(progress.get("added_goals", [])):
        rows.append(
            {
                "section": goal["section"],
                "goal": goal["goal"],
                "depth": goal.get("depth", 1),
                "parent": goal.get("parent"),
                "order": after + index,
                "status": goal["status"],
                "note": goal.get("note", ""),
                "milestone": goal.get("milestone", ""),
                "since": goal.get("since", ""),
            }
        )
    return rows


def join_goals(goals: list[dict], tracked: dict[str, dict]) -> list[dict]:
    rows = []
    for goal in goals:
        entry = tracked.get(key(goal["goal"]))
        rows.append(
            {
                **goal,
                "status": entry["status"] if entry else "untracked",
                "note": entry.get("note", "") if entry else "Added to the log; not tracked yet.",
                "milestone": entry.get("milestone", "") if entry else "",
                "since": entry.get("since", "") if entry else "",
            }
        )
    return rows


# The project.


def questions() -> tuple[list[dict], list[dict], list[dict]]:
    bank = json.loads((ROOT / "server" / "questions" / "questions.json").read_text(encoding="utf-8"))
    by_category: dict[tuple[str, str], Counter] = {}
    for q in bank:
        kind = q.get("kind", "standard")
        counts = by_category.setdefault((q["category"], kind), Counter())
        counts["total"] += 1
        counts["servable" if q["status"] in SERVABLE_STATUSES and q.get("answer") else "not_servable"] += 1
    categories = [
        {"category": category, "kind": kind, "servable": c["servable"], "total": c["total"]}
        for (category, kind), c in sorted(by_category.items())
    ]
    statuses = Counter(q["status"] for q in bank)
    status_rows = [{"status": s, "questions": statuses[s]} for s in ("verified", "agent_verified", "needs_review", "disputed", "unverified")]
    checks = Counter(
        (q["verification"].get("checked_at", ""), q["verification"].get("model", ""))
        for q in bank
        if q.get("verification")
    )
    runs = [{"date": d, "model": m, "questions_checked": n} for (d, m), n in sorted(checks.items())]
    return categories, status_rows, runs


def verifier_spend() -> list[dict]:
    """Runs the verifier logged with their cost (from Nov 10, 2026; earlier runs weren't)."""
    if not RUN_LOG.is_file():
        return []
    return [json.loads(line) for line in RUN_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]


def model_rates() -> list[dict]:
    uses = {"haiku": "Bulk question checks", "sonnet": "Default verifier model", "opus": "Hard cases"}
    return [
        {
            "model": m.id,
            "use": uses.get(name, ""),
            "input_per_million_usd": m.dollars_per_million_input,
            "output_per_million_usd": m.dollars_per_million_output,
            "web_search_per_thousand_usd": DOLLARS_PER_SEARCH * 1000,
        }
        for name, m in MODELS.items()
    ]


def stack() -> list[dict]:
    rows = [{"layer": "Runtime", "tool": "Python", "version": sys.version.split()[0], "role": "Server language (3.12 in production)"}]
    for layer, package, role in SERVER_PACKAGES:
        try:
            version = metadata.version(package)
        except metadata.PackageNotFoundError:
            version = ""
        rows.append({"layer": layer, "tool": package, "version": version, "role": role})
    rows.append({"layer": "Server", "tool": "SQLite", "version": __import__("sqlite3").sqlite_version, "role": "Accounts, saved games and social data, in one file"})
    lock = json.loads((ROOT / "client" / "package-lock.json").read_text(encoding="utf-8"))
    for package, (layer, role) in CLIENT_PACKAGES.items():
        version = lock.get("packages", {}).get(f"node_modules/{package}", {}).get("version", "")
        rows.append({"layer": layer, "tool": package, "version": version, "role": role})
    for line in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines():
        if line.startswith("FROM "):
            image = line.split()[1]
            rows.append({"layer": "Deploy", "tool": f"Docker image {image}", "version": image.split(":")[-1], "role": "Builds the client" if "node" in image else "Runs the server"})
    fly = (ROOT / "fly.toml").read_text(encoding="utf-8")
    size = re.search(r'size = "([^"]+)"', fly)
    memory = re.search(r'memory = "([^"]+)"', fly)
    region = re.search(r'primary_region = "([^"]+)"', fly)
    rows.append({"layer": "Deploy", "tool": "Fly Machine", "version": f"{size.group(1) if size else ''} {memory.group(1) if memory else ''}".strip(), "role": f"One instance in {region.group(1) if region else '?'}, stopped when idle"})
    return rows


def test_count() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT, capture_output=True, text=True, timeout=300
    )
    found = re.search(r"(\d+) tests? collected", result.stdout)
    return int(found.group(1)) if found else 0


def code_size() -> tuple[int, int]:
    files = [
        p
        for folder in (ROOT / "server", ROOT / "client" / "src")
        for p in folder.rglob("*")
        if p.suffix in {".py", ".ts", ".tsx", ".css"} and "node_modules" not in p.parts
    ]
    return len(files), sum(len(p.read_text(encoding="utf-8", errors="ignore").splitlines()) for p in files)


PRODUCTION_QUERY = """
import sqlite3, json
c = sqlite3.connect("file:/data/almanac.db?mode=ro", uri=True)
one = lambda sql: c.execute(sql).fetchone()[0]
print(json.dumps({
 "accounts": one("select count(*) from users"),
 "games": one("select count(*) from games"),
 "coins_held": one("select coalesce(sum(coins),0) from users"),
 "friendships": one("select count(*) from friendships"),
 "groups": one("select count(*) from groups"),
 "push_devices": one("select count(*) from push_subscriptions"),
 "per_day": [{"date": d, "games": g, "seats": s} for d, g, s in c.execute(
   "select substr(g.ended_at,1,10), count(*), coalesce(sum((select count(*) from game_players p where p.game_id=g.id)),0) from games g group by 1 order by 1")],
}))
"""


def production() -> dict | None:
    """Aggregate counts from the live database, read-only, over Fly SSH. None if unreachable."""
    encoded = base64.b64encode(PRODUCTION_QUERY.encode()).decode()
    command = ["flyctl", "ssh", "console", "-a", "almanac-game", "-C", f"python -c \"import base64;exec(base64.b64decode('{encoded}'))\""]
    for _ in range(3):
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
        if result.returncode == 0 and lines:
            return json.loads(lines[-1])
    return None


# Putting it together.


def build(with_production: bool) -> dict:
    progress = json.loads((HERE / "progress.json").read_text(encoding="utf-8"))
    services = json.loads((HERE / "services.json").read_text(encoding="utf-8"))
    principles, goals = dev_log()
    goal_rows = join_goals(goals, progress["goals"])
    goal_rows += added_goals(progress, len(goal_rows))
    categories, status_rows, runs = questions()
    files, lines = code_size()
    today = date.today().isoformat()
    previous = json.loads(OUT.read_text(encoding="utf-8")) if OUT.is_file() else {}
    usage = production() if with_production else None
    usage = usage or previous.get("production")
    goal_status = Counter(row["status"] for row in goal_rows)
    milestone_status = Counter(m["status"] for m in progress["milestones"])
    servable = sum(row["servable"] for row in categories)
    snapshot = {
        "date": today,
        "goals_done": goal_status["done"],
        "goals_total": len(goal_rows),
        "milestones_done": milestone_status["done"],
        "milestones_total": len(progress["milestones"]),
        "tests": test_count(),
        "code_files": files,
        "code_lines": lines,
        "questions_servable": servable,
        "questions_total": sum(row["total"] for row in categories),
        "case_questions_servable": sum(row["servable"] for row in categories if row["kind"] == "case"),
        "accounts": usage["accounts"] if usage else None,
        "games": usage["games"] if usage else None,
    }
    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.is_file() else []
    history = [row for row in history if row["date"] != today] + [snapshot]
    cost_rows = services["costs"]
    data = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "principles": [{"order": i, "principle": p} for i, p in enumerate(principles)],
        "goals": goal_rows,
        "milestones": progress["milestones"],
        "timeline": progress["timeline"],
        "snapshot": [snapshot],
        "history": history,
        "questions_by_category": categories,
        "questions_by_status": status_rows,
        "verifier_checks": runs,
        "verifier_spend": verifier_spend(),
        "model_rates": model_rates(),
        "costs": cost_rows,
        "cost_summary": [
            {
                "monthly_max_usd": round(sum(row["monthly_max_usd"] for row in cost_rows), 2),
                "fly_waiver_usd": services["fly_waiver_usd"],
                "revenue_usd": 0,
                "prices_checked": services["prices_checked"],
            }
        ],
        "services": services["services"],
        "stack": stack(),
        "production": usage,
    }
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production", action="store_true", help="also read aggregate counts from the live database")
    args = parser.parse_args()
    data = build(args.production)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    HISTORY.write_text(json.dumps(data["history"], indent=1), encoding="utf-8")
    snap = data["snapshot"][0]
    for_app = {name: data[name] for name in APP_KEYS}
    for_app["snapshot"] = [{name: snap[name] for name in APP_SNAPSHOT_KEYS}]  # the server counts its own accounts and questions
    APP_COPY.write_text(json.dumps(for_app, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    untracked = [g["goal"] for g in data["goals"] if g["status"] == "untracked"]
    print(f"wrote {OUT.relative_to(ROOT)}: {snap['goals_done']}/{snap['goals_total']} goals done, "
          f"{snap['milestones_done']}/{snap['milestones_total']} milestones, {snap['tests']} tests, "
          f"{snap['questions_servable']} servable questions")
    print(f"wrote {APP_COPY.relative_to(ROOT)}: the plans and services the app's overview page shows after the next deploy")
    if untracked:
        print("untracked goals (add them to progress.json):", "; ".join(untracked))
    return 0


if __name__ == "__main__":
    sys.exit(main())
