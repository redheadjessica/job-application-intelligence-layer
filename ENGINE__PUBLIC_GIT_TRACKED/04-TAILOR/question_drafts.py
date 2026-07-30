#!/usr/bin/env python3
"""question_drafts.py — mechanical scaffolding for the Application Question Drafts
section of a tailored-resume output.

The tailoring agent appends `## Application Question Drafts` to
`application_resume_output…md`. The SKELETON of that section — which questions, in
what order, with the exact question text preserved and each question's class-specific
drafting instruction — is generated HERE, mechanically from the capture, so the agent
fills in answers under headings it cannot re-word, re-order, or drop. (An agent
composing the scaffold freely is how filenames diverged; derived scaffolds are the
lesson.)

Per question class (annotated by ats_fetchers.classify_question):
  substantive — a concise distilled answer drawn ONLY from the candidate's profile,
                approved evidence, the JD, and voice guidance. Never invent
                experience or facts.
  logistical  — NOT an essay: guidance on how to answer, plus exactly what the
                candidate must confirm (an unknown factual/logistical answer states
                what needs confirming rather than guessing).

With no captured questions the section reads `None Found`.

    python ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/question_drafts.py <capture.txt>
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "02-PREP"))

from ats_fetchers import (  # noqa: E402
    QUESTION_LOGISTICAL,
    QUESTION_STANDARD,
    QUESTION_SUBSTANTIVE,
    classify_question,
)

SECTION_HEADING = "## Application Question Drafts"
NONE_FOUND = "None Found"
_QUESTIONS_BANNER = "APPLICATION QUESTIONS WORTH PREPARING"
_BODY_START = "--- JOB TEXT START ---"
_QUESTION_LINE_RE = re.compile(r"^(\d+)\.\s+(.+?)\s\[(Required|Optional)\]$")
_CONTEXT_LINE_RE = re.compile(r"^\s{3}(\[[^\]]+\])$")

_SUBSTANTIVE_STUB = (
    "*(substantive — draft ONE concise answer below, drawn only from the candidate's "
    "profile, approved evidence, the job description, and voice guidance. Never invent "
    "experience or facts; route any unverified fact into \"Questions for the "
    "candidate\".)*")
_LOGISTICAL_STUB = (
    "*(logistical — do NOT draft an essay. Give brief guidance on how to answer, and "
    "state exactly what the candidate must confirm before submitting — e.g. which "
    "office/location/date applies. If the true answer is unknown, say precisely what "
    "needs confirming rather than guessing.)*")


def parse_capture_questions(text: str) -> list[dict]:
    """The captured questions, exactly as written: [{number, label, required,
    context: [bracketed lines]}]. Empty when the section reads `None Found.`"""
    text = str(text or "")
    if _QUESTIONS_BANNER not in text:
        return []
    section = text.split(_QUESTIONS_BANNER, 1)[1]
    section = section.split(_BODY_START, 1)[0]
    out: list[dict] = []
    for raw in section.split("\n"):
        m = _QUESTION_LINE_RE.match(raw)
        if m:
            out.append({"number": int(m.group(1)), "label": m.group(2),
                        "required": m.group(3) == "Required", "context": []})
            continue
        c = _CONTEXT_LINE_RE.match(raw)
        if c and out:
            out[-1]["context"].append(c.group(1))
    return out


def drafts_skeleton(capture_text: str) -> str:
    """The Application Question Drafts section skeleton for one capture: exact
    question text preserved in each heading, class-specific drafting instruction
    under it, `None Found` when the capture holds no questions. Standard fields
    (which the prep filter should never have captured) are skipped with a note
    rather than answered."""
    questions = parse_capture_questions(capture_text)
    lines = [SECTION_HEADING, ""]
    if not questions:
        lines.append(NONE_FOUND)
        return "\n".join(lines) + "\n"
    for q in questions:
        cls = classify_question({"label": q["label"]})
        marker = "[Required]" if q["required"] else "[Optional]"
        lines.append(f"### Q{q['number']}: {q['label']} {marker}")
        for ctx in q["context"]:
            lines.append(f"> {ctx}")
        if cls == QUESTION_STANDARD:
            lines.append("*(standard field — no draft; it should not have been "
                         "captured. Note it in \"Suggested System Updates\".)*")
        elif cls == QUESTION_SUBSTANTIVE:
            lines.append(_SUBSTANTIVE_STUB)
        else:
            lines.append(_LOGISTICAL_STUB)
        lines.append("")
        lines.append("(draft here)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv):
    parser = argparse.ArgumentParser(
        description="Print the Application Question Drafts skeleton for a capture.")
    parser.add_argument("capture", help="the job capture .txt")
    args = parser.parse_args(argv[1:])
    print(drafts_skeleton(Path(args.capture).read_text(encoding="utf-8")), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
