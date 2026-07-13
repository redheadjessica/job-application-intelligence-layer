"""Deterministic changelog structure logic for JAIL's changelog synthesis.

Pure functions only — no Git, no network, no filesystem. `doc_synthesis.py` is the
runner that wires these into a live pass. Kept separate so the parsing/sorting/marker
rules can be exercised by fast, offline tests.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

DATED_HEADING = re.compile(
    r"^## (\d{4}-\d{2}-\d{2})(?: to (?:(\d{4}-\d{2}-\d{2})|(\d{2})))? — (.+)$"
)
PRE_HISTORY_HEADING = re.compile(r"^## Pre-\d{4}-\d{2}-\d{2} — ")
HEADING_LINE = re.compile(r"^## .+$", re.MULTILINE)
MARKER_RE = re.compile(r"<!-- changelog-processed-through: ([0-9a-f]{7,40}) -->")


@dataclass(frozen=True)
class Heading:
    kind: str  # "dated" | "pre-history" | "earlier" | "unknown"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    title: Optional[str] = None


def _date_key(value: str) -> int:
    return int(value.replace("-", ""))


def _expand_end_date(start_date: str, full_end_date: Optional[str], short_end_day: Optional[str]) -> str:
    if full_end_date:
        return full_end_date
    if short_end_day:
        return f"{start_date[:8]}{short_end_day}"
    return start_date


def parse_heading(heading: str) -> Heading:
    match = DATED_HEADING.match(heading)
    if match:
        start_date, full_end_date, short_end_day, title = match.groups()
        end_date = _expand_end_date(start_date, full_end_date, short_end_day)
        if _date_key(end_date) < _date_key(start_date):
            raise ValueError(f"Changelog date range ends before it starts: {heading}")
        return Heading(kind="dated", start_date=start_date, end_date=end_date, title=title)

    if PRE_HISTORY_HEADING.match(heading):
        return Heading(kind="pre-history")

    if heading.startswith("## Earlier — "):
        return Heading(kind="earlier")

    return Heading(kind="unknown")


@dataclass(frozen=True)
class Section:
    text: str
    heading: str
    original_index: int
    kind: str
    start_date: Optional[str]
    end_date: Optional[str]
    title: Optional[str]


@dataclass(frozen=True)
class ParsedChangelog:
    preamble: str
    sections: list


def parse_changelog(markdown: str) -> ParsedChangelog:
    heading_matches = list(HEADING_LINE.finditer(markdown))
    if not heading_matches:
        raise ValueError("Changelog has no level-two entry headings.")

    preamble = markdown[: heading_matches[0].start()].rstrip()
    sections = []
    for index, match in enumerate(heading_matches):
        start = match.start()
        end = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(markdown)
        text = markdown[start:end].strip()
        parsed = parse_heading(match.group(0))
        sections.append(
            Section(
                text=text,
                heading=match.group(0),
                original_index=index,
                kind=parsed.kind,
                start_date=parsed.start_date,
                end_date=parsed.end_date,
                title=parsed.title,
            )
        )

    return ParsedChangelog(preamble=preamble, sections=sections)


def _section_rank(section: Section) -> int:
    if section.kind == "dated":
        return 0
    if section.kind == "pre-history":
        return 1
    if section.kind == "earlier":
        return 2
    return 3


def sort_sections(sections: list) -> list:
    def sort_key(section: Section):
        rank = _section_rank(section)
        if section.kind == "dated":
            return (rank, -_date_key(section.end_date), -_date_key(section.start_date), section.original_index)
        return (rank, 0, 0, section.original_index)

    return sorted(sections, key=sort_key)


def normalize_changelog(markdown: str) -> str:
    parsed = parse_changelog(markdown)
    unknown = [s for s in parsed.sections if s.kind == "unknown"]
    if unknown:
        headings = ", ".join(s.heading for s in unknown)
        raise ValueError(f"Unsupported changelog heading(s): {headings}")

    pre_history_count = sum(1 for s in parsed.sections if s.kind == "pre-history")
    earlier_count = sum(1 for s in parsed.sections if s.kind == "earlier")
    if pre_history_count != 1 or earlier_count != 1:
        raise ValueError("Changelog must contain exactly one Pre-history section and one Earlier section.")

    body = "\n\n".join(section.text for section in sort_sections(parsed.sections))
    return f"{parsed.preamble}\n\n{body}\n"


def get_processed_commit(markdown: str) -> Optional[str]:
    match = MARKER_RE.search(markdown)
    return match.group(1) if match else None


def set_processed_commit(markdown: str, commit: str) -> str:
    marker = f"<!-- changelog-processed-through: {commit} -->"
    if MARKER_RE.search(markdown):
        return MARKER_RE.sub(marker, markdown)

    divider_index = markdown.find("\n---")
    if divider_index >= 0:
        return f"{markdown[:divider_index]}\n\n{marker}{markdown[divider_index:]}"

    first_entry_match = re.search(r"^## ", markdown, re.MULTILINE)
    if first_entry_match:
        idx = first_entry_match.start()
        return f"{markdown[:idx].rstrip()}\n\n{marker}\n\n{markdown[idx:]}"

    raise ValueError("Cannot insert changelog marker because no entry heading exists.")


# Paths JAIL's own synthesis maintenance touches. Kept separate from product-facing
# engine/doc paths so a synthesis-only commit never re-triggers itself.
_SYNTHESIS_MAINTENANCE_PATHS = frozenset(
    {
        "docs/changelog.md",
        "docs/doc-status.md",
        "scripts/doc_synthesis.py",
        "scripts/doc_synthesis_core.py",
        "scripts/README.md",
        "tests/test_doc_synthesis_core.py",
    }
)


def meaningful_changed_files(files: list) -> list:
    """Filter Git-changed paths down to ones worth synthesizing.

    Mirrors Ascend's doc-synthesis-core.js: a synthesis-only commit (touching only the
    changelog, the drift report, or the synthesis scripts/tests/README) never counts as
    meaningful work, so it can never trigger itself. When synthesis code changed as part
    of a bigger commit, requirements.txt is also treated as synthesis maintenance (it is
    JAIL's dependency manifest, edited alongside tooling changes, not product work).
    """
    includes_synthesis_code = any(f.startswith("scripts/doc_synthesis") for f in files)
    ignored = set(_SYNTHESIS_MAINTENANCE_PATHS)
    if includes_synthesis_code:
        ignored.add("requirements.txt")
    return [f for f in files if f not in ignored]
