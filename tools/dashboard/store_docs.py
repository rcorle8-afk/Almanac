"""Writes the dashboard's store documents as JSON files, ready for an ArtifactData batch.

    python tools/dashboard/store_docs.py --asset-url /_blob/<id> [--page]

Each source on the dashboard is one key of the uploaded almanac-dashboard.json (refresh.py
writes it). After a refresh, Claude uploads that file to the dashboard, runs this with the new
upload's url, and writes the files in out/store/ with one batch: every dataset points at the new
file and says when it was updated. --page also writes the page (page/index.html).
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
STORE = HERE / "out" / "store"
FILE_NAME = "almanac-dashboard.json"
SCHEDULE = "Rebuilt from the project by tools/dashboard/refresh.py whenever Claude ships a change, and uploaded here."
STALE_AFTER_HOURS = 24 * 7

DATASETS = {
    "goals": ("Development log goals", "Every goal in Almanac Development Log.docx, in order, with its status from tools/dashboard/progress.json."),
    "milestones": ("Milestones", "M0 to M6 from the spec, each with its status, ship date and what's still open."),
    "timeline": ("What shipped when", "The main releases by date, from the spec's history."),
    "principles": ("Principles from the log", "The two lines at the top of the development log."),
    "snapshot": ("Latest snapshot", "Counts worked out from the project at the last refresh: goals, milestones, tests, code size and questions."),
    "history": ("Snapshot history", "One snapshot per refresh day, kept in tools/dashboard/history.json."),
    "questions_by_category": ("Questions by category", "Questions in server/questions/questions.json by category and kind, and how many games may serve."),
    "questions_by_status": ("Questions by status", "Every question in the bank by verification status."),
    "verifier_checks": ("Verifier runs", "How many questions each verifier run checked, by date and model, from the verification records in the bank."),
    "verifier_spend": ("Verifier spend", "Tokens, searches and cost of each verifier run, logged in server/questions/verify_runs.jsonl from Nov 10, 2026."),
    "model_rates": ("Claude model rates", "The per-token and per-search rates the verifier uses to price its runs (server/questions/verify.py)."),
    "costs": ("Sample: monthly cost ceilings", "Estimated, not billed: each line's most per month, worked out from Fly.io's published price list and the app's setup (tools/dashboard/services.json)."),
    "cost_summary": ("Sample: cost summary", "Estimated, not billed: the sum of the cost ceilings, Fly's $5 waiver for personal organizations, and revenue (none, by design)."),
    "services": ("Outside services", "The services Almanac relies on, what each does, how it's set up and what it costs (tools/dashboard/services.json)."),
    "stack": ("Tools and versions", "The server's and client's packages at their installed versions, and the images Fly builds from."),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-url", required=True, help="the /_blob/<id> url the upload returned")
    parser.add_argument("--page", action="store_true", help="also write the page")
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    STORE.mkdir(parents=True, exist_ok=True)
    edit = {"via": "claude", "at": now}
    for dataset_id, (title, description) in DATASETS.items():
        document = {
            "title": title,
            "description": description,
            "source": {"kind": "file", "url": args.asset_url, "name": FILE_NAME, "format": "json"},
            "updated": {"at": now, "by": "Claude, from tools/dashboard/refresh.py"},
            "schedule": SCHEDULE,
            "staleAfterHours": STALE_AFTER_HOURS,
            "edit": edit,
        }
        (STORE / f"datasets__{dataset_id}.json").write_text(json.dumps(document), encoding="utf-8")
    (STORE / "dash__meta.json").write_text(json.dumps({"title": "Almanac Dashboard", "lang": "en"}), encoding="utf-8")
    if args.page:
        page = (HERE / "page" / "index.html").read_text(encoding="utf-8")
        (STORE / "files__index.html.json").write_text(json.dumps({"text": page, "edit": edit}), encoding="utf-8")
    print(f"wrote {len(list(STORE.glob('*.json')))} documents to {STORE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
