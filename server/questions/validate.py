"""Schema and status checks for the question bank.

    python -m server.questions.validate              # fail on any bad entry
    python -m server.questions.validate --require 30 # also fail under 30 servable
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from pydantic import TypeAdapter

from server.engine.models import Question

BANK_PATH = Path(__file__).with_name("questions.json")
SERVABLE_STATUSES = ("verified", "agent_verified")
# What a case question carries on top of the usual fields: its setup, its hint, and for each
# the page and the sentence that state its figure.
CASE_FIELDS = (
    "context",
    "context_source_url",
    "context_source_quote",
    "hint_text",
    "hint_source_url",
    "hint_source_quote",
)


def load_bank(path: Path = BANK_PATH) -> list[Question]:
    return TypeAdapter(list[Question]).validate_json(path.read_bytes())


def check_bank(questions: list[Question]) -> list[str]:
    problems = []
    counts = Counter(question.id for question in questions)
    problems += [f"{id_}: duplicate id" for id_, count in counts.items() if count > 1]
    for question in questions:
        if question.status in SERVABLE_STATUSES:
            missing = [
                field
                for field in ("answer", "source_url", "as_of")
                if not getattr(question, field)
            ]
            if missing:
                problems.append(f"{question.id}: verified without {', '.join(missing)}")
        if question.status == "agent_verified" and not question.verification:
            problems.append(f"{question.id}: agent_verified without evidence")
        extras = [field for field in CASE_FIELDS if getattr(question, field)]
        if question.kind == "case":
            missing = [field for field in CASE_FIELDS if field not in extras]
            if missing:
                problems.append(f"{question.id}: case question without {', '.join(missing)}")
        elif extras:
            problems.append(f"{question.id}: {', '.join(extras)} on a question that isn't a case")
    return problems


def servable(questions: list[Question], allow_unverified: bool = False) -> list[Question]:
    """Questions a game may use. allow_unverified is for local playtests only."""
    return [
        question
        for question in questions
        if question.answer is not None
        and (question.status in SERVABLE_STATUSES or allow_unverified)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require", type=int, default=0, help="minimum servable questions")
    args = parser.parse_args()

    questions = load_bank()
    problems = check_bank(questions)
    ready = len(servable(questions))
    if ready < args.require:
        problems.append(f"{ready} servable questions, {args.require} required")
    for problem in problems:
        print(f"FAIL {problem}")
    counts = Counter(question.status for question in questions)
    print(f"{len(questions)} questions, {ready} servable: {dict(counts)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
