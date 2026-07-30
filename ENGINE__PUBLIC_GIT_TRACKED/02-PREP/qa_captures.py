#!/usr/bin/env python3
"""qa_captures.py — the permanent acceptance gate for saved job captures.

Validates every capture against the FROZEN output contract (JOB SNAPSHOT format,
2026-07-30) and against every defect class the live 55-job run actually produced.
Runs standalone over files/folders, and automatically at the end of every prep run
(`prep_common.process_urls` calls it for each capture it wrote): a failing capture
is LOUDLY reported and quarantined — it never silently joins a batch as usable.

DELIBERATELY SELF-CONTAINED: this module re-implements its checks from the contract
spec rather than importing the writer's own helpers. A validator that shares the
writer's code inherits the writer's bugs; an independent implementation is the point.
(The two are pinned against each other by the test suite.)

Checks (each maps to a real defect class — see tests/test_qa_captures.py):
  filename shape · section presence+order · banner underlines · Title Case labels ·
  required fields populated (value or Unknown) · working-location / office-expectation
  structure · compensation structure (inline single band vs bulleted multi-band) ·
  question-section grammar · ORIGINAL/LATEST sanity (LATEST never without ORIGINAL,
  ORIGINAL ≤ LATEST) · no fused text · no legacy markers · minimum body length +
  recognizable JD structure · no standard/demographic fields in the questions section ·
  no application-choice text (Yes/No) in location fields · no false absence claims
  (a header must not say "Employer did not mention …" when the body plainly contains
  a benefits section or a base-salary band).
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------- #
# Contract constants (independent re-statement of the frozen spec)
# --------------------------------------------------------------------------- #
SECTIONS = ["JOB SNAPSHOT", "WORK DETAILS", "COMPENSATION",
            "APPLICATION QUESTIONS WORTH PREPARING"]
START_MARKER = "--- JOB TEXT START ---"
END_MARKER = "--- JOB TEXT END ---"
ORIGINAL_BANNER = "ORIGINAL CAPTURE DETAILS"
LATEST_BANNER = "LATEST CAPTURE DETAILS"

SNAPSHOT_LABELS = ["Company", "Role", "Job Posting URL", "Job Posted At", "Job Updated At"]
WORK_LABELS = ["Employment", "Work Arrangement", "Working Location(s)", "Office Expectation"]
COMP_LABELS = ["Base Salary", "Additional Compensation", "Benefits"]
DETAILS_LABELS = ["Captured At", "Application URL", "Source", "Posting ATS ID",
                  "Methods Checked"]
OPTIONAL_LABELS = {"Location Preference"}

MIN_BODY_CHARS = 700
_JD_STRUCTURE_MARKERS = (
    "responsib", "requirement", "qualificat", "what you", "about the role",
    "about the job", "you'll", "you will", "experience", "we're looking",
    "what we", "the role",
)

LEGACY_MARKERS = (
    "== NORMALIZED", "== APPLICATION QUESTIONS", "== EMPLOYER-PROVIDED",
    "[found]", "[not posted]", "[capture failed]", "[capture_failed]", "[conflicting]",
    '(verbatim): ""', "Re-Captured:", "Employer apply page", "CAPTURE UPDATE DETAILS",
    "Completeness: title",
)

# The specific fusion shapes hit live, plus the generic boundary guard.
FUSION_SHAPES = ("Role Details:Employment", "ExemptThis", "will:Growth")
_FUSION_RE = re.compile(r"[a-z]{3}:[A-Z][a-z]{3}")
_URL_SCHEME_RE = re.compile(r"(?i)(?:https?|mailto|ftp|tel):")

# Standard/demographic field labels that must never appear as captured questions.
_STANDARD_FIELD_RE = re.compile(
    r"(?im)^\s*\d+\.\s.*\b("
    r"first name|last name|full name|e-?mail|phone|resume|cv\b|cover letter|linkedin"
    r"|portfolio url|website|pronouns"
    r"|gender|race|ethnicity|veteran|disability|sexual orientation"
    r"|authorized to work|work authorization|visa|sponsorship"
    r"|how did you hear|where did you find"
    r")\b")

# Application-choice text that must never sit in a location field (the live class:
# a Yes/No office-attendance ANSWER leaked into Working Location(s)).
_CHOICE_TEXT_RE = re.compile(r"(?i)^(yes|no)\b|\byes\s*/\s*no\b|\byes or no\b")

# Body evidence of a benefits section / a base-salary band, for the false-absence check.
_BODY_BENEFITS_HEADING_RE = re.compile(
    r"(?im)^[\s#>*\-]*(?:(?:full[-\s]?time|part[-\s]?time|employee|our|us|team|your)\s+){0,3}"
    r"(?:benefits?|perks?( & benefits)?|what we offer)\b[.:]?\s*$")
_BODY_SALARY_BAND_RE = re.compile(
    r"(?i)(?:salary|compensation|pay)\D{0,80}\$\s?\d[\d,.]*\s?(?:k\b|,\d{3})"
    r"|\$\s?\d[\d,.]*\s?(?:k\b|,\d{3})?\s?(?:-|–|—|to)\s?\$?\s?\d[\d,.]*")

_FILENAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*__[a-z0-9][a-z0-9-]*(?:-[a-z0-9]+)?\.txt$")
_QUESTION_LINE_RE = re.compile(r"^\d+\.\s+.+\s\[(Required|Optional)\]$")
_CONTEXT_LINE_RE = re.compile(r"^\s{3}\[(Context|Options|Locations|Office Expectation|Address):\s.*\]$")
_CAPTURED_AT_RE = re.compile(
    r"^Captured At:\s+([A-Z][a-z]+ \d{1,2}, \d{4})(?: at (\d{1,2}:\d{2} [AP]M) ET| — Time Unavailable)$")


def _parse_captured_at(line: str):
    m = _CAPTURED_AT_RE.match(line.strip())
    if not m:
        return None
    try:
        d = datetime.strptime(m.group(1), "%B %d, %Y")
    except ValueError:
        return None
    if m.group(2):
        t = datetime.strptime(m.group(2), "%I:%M %p")
        d = d.replace(hour=t.hour, minute=t.minute)
    return d


def _grab(head: str, label: str):
    # [ \t]* not \s*: \s matches the newline, which let a BLANK field swallow the
    # next line as its value and pass the populated-field check.
    m = re.search(rf"^{re.escape(label)}:[ \t]*(.*)$", head, re.M)
    return m.group(1).strip() if m else None


def validate_capture(text: str, filename: str | None = None) -> list[str]:
    """Every contract violation in one capture, as human-readable problem strings.
    Empty list == the capture passes the gate."""
    problems: list[str] = []
    text = str(text or "")
    lines = text.split("\n")

    # ---- filename shape -------------------------------------------------- #
    if filename is not None and not _FILENAME_RE.match(str(filename)):
        problems.append(f"filename not canonical `company__role.txt` slug: {filename!r}")

    # ---- section presence + order + banner underlines --------------------- #
    order_targets = SECTIONS + [START_MARKER, END_MARKER, ORIGINAL_BANNER]
    positions = {}
    for target in order_targets + [LATEST_BANNER]:
        idx = text.find(f"{target}\n") if target not in (START_MARKER, END_MARKER) \
            else text.find(target)
        positions[target] = idx
    missing = [t for t in order_targets if positions[t] < 0]
    if missing:
        problems.append("missing section(s): " + ", ".join(missing))
    else:
        found = [t for t in order_targets if positions[t] >= 0]
        if [t for t, _ in sorted(((t, positions[t]) for t in found), key=lambda kv: kv[1])] != found:
            problems.append("sections out of order (contract: JOB SNAPSHOT → WORK DETAILS → "
                            "COMPENSATION → QUESTIONS → JOB TEXT → ORIGINAL CAPTURE DETAILS)")
    for banner, ch in ([(s, "=") for s in SECTIONS]
                       + [(ORIGINAL_BANNER, "-"), (LATEST_BANNER, "-")]):
        if positions.get(banner, -1) < 0:
            continue
        try:
            i = lines.index(banner)
        except ValueError:
            continue
        if i + 1 >= len(lines) or lines[i + 1] != ch * len(banner):
            problems.append(f"banner underline wrong for {banner!r}")

    head = text.split(START_MARKER, 1)[0]
    body = ""
    tail = ""
    if START_MARKER in text and END_MARKER in text:
        body = text.split(START_MARKER, 1)[1].split(END_MARKER, 1)[0].strip("\n")
        tail = text.split(END_MARKER, 1)[1]

    # ---- legacy markers ---------------------------------------------------- #
    for marker in LEGACY_MARKERS:
        if marker in text:
            problems.append(f"legacy marker present: {marker!r}")

    # ---- required fields populated (Title Case labels) --------------------- #
    for label in SNAPSHOT_LABELS + WORK_LABELS:
        val = _grab(head, label)
        if val is None:
            problems.append(f"missing field label: {label}:")
        elif not val:
            problems.append(f"field blank (must hold a value or Unknown): {label}:")
    base_salary_inline = _grab(head, "Base Salary")
    if base_salary_inline is None and not re.search(r"^Base Salary:\s*$", head, re.M):
        problems.append("missing field label: Base Salary:")
    for label in ("Additional Compensation", "Benefits"):
        val = _grab(head, label)
        if val is None:
            problems.append(f"missing field label: {label}:")
        elif not val:
            problems.append(f"field blank: {label}:")
    if tail:
        original_chunk = tail.split(LATEST_BANNER)[0]
        for label in DETAILS_LABELS:
            if _grab(original_chunk, label) is None:
                problems.append(f"missing ORIGINAL detail label: {label}:")
        if "Verification:" not in original_chunk:
            problems.append("missing ORIGINAL detail label: Verification:")

    # ---- compensation structure -------------------------------------------- #
    m = re.search(r"^Base Salary:[ \t]*\n((?:- .*\n)+)", head, re.M)
    if m:
        bullets = [b for b in m.group(1).splitlines() if b.strip()]
        if len(bullets) == 1:
            problems.append("Base Salary: a SINGLE band must render inline, not as a "
                            "one-item bullet list")
    elif base_salary_inline is not None and base_salary_inline == "":
        problems.append("Base Salary: label present but neither inline value nor bullets")

    # ---- working-location / office-expectation structure -------------------- #
    wl = _grab(head, "Working Location(s)") or ""
    office = _grab(head, "Office Expectation") or ""
    for name, val in (("Working Location(s)", wl), ("Office Expectation", office)):
        if val and _CHOICE_TEXT_RE.search(val):
            problems.append(f"{name}: application-choice text leaked into a location "
                            f"field: {val!r}")
    if office and office != "Not Specified" and not re.search(
            r"(?i)\d+\s*\+?\s*day|per week|per month|a week|at least", office):
        problems.append(f"Office Expectation: not a stated cadence and not "
                        f"`Not Specified`: {office!r}")

    # ---- questions section -------------------------------------------------- #
    if positions.get(SECTIONS[3], -1) >= 0 and START_MARKER in text:
        qsection = text.split(SECTIONS[3], 1)[1].split(START_MARKER, 1)[0]
        qlines = [l for l in qsection.split("\n")[2:] if l.strip()]
        if not qlines:
            problems.append("questions section empty (must hold questions or `None Found.`)")
        elif qlines != ["None Found."]:
            for ql in qlines:
                if ql == "None Found.":
                    problems.append("`None Found.` mixed with question lines")
                elif not (_QUESTION_LINE_RE.match(ql) or _CONTEXT_LINE_RE.match(ql)):
                    problems.append(f"question line off-grammar: {ql!r}")
        m = _STANDARD_FIELD_RE.search(qsection)
        if m:
            problems.append(f"standard/demographic field leaked into questions: "
                            f"{m.group(0).strip()!r}")

    # ---- ORIGINAL / LATEST sanity -------------------------------------------- #
    if positions.get(LATEST_BANNER, -1) >= 0 and positions.get(ORIGINAL_BANNER, -1) < 0:
        problems.append("LATEST CAPTURE DETAILS present without ORIGINAL CAPTURE DETAILS")
    if tail and LATEST_BANNER in tail:
        chunks = tail.split(LATEST_BANNER)
        orig_line = _grab(chunks[0], "Captured At")
        latest_line = _grab(chunks[1], "Captured At")
        d_orig = _parse_captured_at(f"Captured At: {orig_line}") if orig_line else None
        d_latest = _parse_captured_at(f"Captured At: {latest_line}") if latest_line else None
        if d_orig and d_latest and d_orig > d_latest:
            problems.append(f"ORIGINAL Captured At ({orig_line}) is AFTER LATEST "
                            f"({latest_line}) — the original is immutable and earliest")
        if "Additional Notes:" not in chunks[1]:
            problems.append("LATEST section missing Additional Notes:")

    # ---- fused text ----------------------------------------------------------- #
    for shape in FUSION_SHAPES:
        if shape in text:
            problems.append(f"known fused-text shape present: {shape!r}")
    for m in _FUSION_RE.finditer(text):
        prefix = text[max(0, m.start() - 8):m.start() + 4]
        if _URL_SCHEME_RE.search(prefix):
            continue  # `https://Foo` style scheme separators are not fusion
        problems.append(f"fused block boundary (no separator): "
                        f"{text[max(0, m.start() - 20):m.end() + 20].strip()!r}")
        break  # one report per file is enough

    # ---- body length + JD structure ------------------------------------------- #
    if START_MARKER in text:
        if len(body) < MIN_BODY_CHARS:
            problems.append(f"body too short ({len(body)} chars, under {MIN_BODY_CHARS})")
        if not any(k in body.lower() for k in _JD_STRUCTURE_MARKERS):
            problems.append("body has no recognizable job-description structure "
                            "(responsibilities/qualifications/about-the-role/…)")

    # ---- false absence claims --------------------------------------------------- #
    benefits_val = (_grab(head, "Benefits") or "")
    if benefits_val.startswith("Employer did not mention") and \
            _BODY_BENEFITS_HEADING_RE.search(body):
        problems.append("false absence: header says employer did not mention benefits, "
                        "but the body contains a benefits section")
    if base_salary_inline and base_salary_inline.startswith("Employer did not mention") and \
            _BODY_SALARY_BAND_RE.search(body):
        problems.append("false absence: header says employer did not mention compensation, "
                        "but the body contains a base-salary band")

    return problems


def validate_file(path) -> list[str]:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"unreadable: {type(exc).__name__}: {exc}"]
    return validate_capture(text, filename=p.name)


def run(targets, out=print) -> int:
    files: list[Path] = []
    for target in targets:
        p = Path(target)
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*.txt") if f.is_file()))
        elif p.is_file():
            files.append(p)
    failed = 0
    for f in files:
        problems = validate_file(f)
        if problems:
            failed += 1
            out(f"✗ {f.name}")
            for pr in problems:
                out(f"    - {pr}")
        else:
            out(f"✓ {f.name}")
    out(f"[qa-captures] {len(files) - failed} passed, {failed} failed of {len(files)}.")
    return 1 if failed else 0


def main(argv):
    parser = argparse.ArgumentParser(description="Acceptance gate for saved job captures.")
    parser.add_argument("targets", nargs="+", help="capture files and/or folders")
    args = parser.parse_args(argv[1:])
    return run(args.targets)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
