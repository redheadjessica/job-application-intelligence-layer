#!/usr/bin/env python3
"""Resolve the AUTHORITATIVE, READABLE file for a resume base — and say so out loud when there
isn't one.

Why this exists. The tailoring engine's normal reading rule is to work from the bullet previews in
`02-resume-index.md` and only open a base file when it needs a verbatim bullet (see
`00-job_application_agent.md`, "Resume-Base Reading Rule"). That is the right default for drafting
recommendations, and exactly the wrong input for SCORING the base: the index is a prose summary a
human wrote about the resume, so scoring it would grade the description rather than the document.
Several anchors in a real index carry only a one-paragraph gist, and at least one says outright that
its contents are not fully indexed.

The complication is that every base in the current setup is an Apple Pages file, which cannot be
read directly. Each finalized base does have a `.pdf` sibling in the same folder, and the index
already names the `.pages`/`.pdf` pair as authoritative — so the PDF is the artifact the comparison
pass reads.

Two failure modes must be visible rather than papered over:
  * NO readable PDF — the base score is left BLANK. It is never estimated from the index, because a
    number sourced from a summary is indistinguishable in the spreadsheet from one sourced from the
    document.
  * A STALE PDF — the `.pages` was edited after the PDF was exported, so the PDF is missing the
    candidate's most recent manual edits. The file is still readable and still scored, but the note
    travels with the score so the number can be discounted.

    python resume_artifacts.py "/path/to/Resume - Company - Role.pages"
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# How much newer the .pages may be before its PDF counts as stale. Exporting a PDF from Pages
# writes the two files seconds apart, so a small window avoids flagging a normal export; anything
# beyond it means real editing happened after the export.
STALE_TOLERANCE_SECONDS = 120

# Formats the comparison pass can read directly, and the tool each one needs. `.pages` is
# deliberately absent — it is the one format with no direct reader, which is the whole reason
# the PDF sibling lookup exists.
DIRECT_READABLE = {
    ".pdf": "pdf skill",
    ".md": "Read tool",
    ".txt": "Read tool",
    ".docx": "docx skill",
}

# Resolution outcomes. Only `ok` and `stale` carry a readable path; the rest mean BLANK scores.
STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_NO_PDF = "no-readable-pdf"
STATUS_NOT_FOUND = "not-found"
SCOREABLE = (STATUS_OK, STATUS_STALE)


@dataclass
class BaseArtifact:
    source: str            # what the resume index pointed at
    readable_path: str | None
    reader: str | None     # which tool opens `readable_path`
    status: str
    note: str

    @property
    def scoreable(self) -> bool:
        return self.status in SCOREABLE

    def to_json(self) -> str:
        d = asdict(self)
        d["scoreable"] = self.scoreable
        return json.dumps(d, indent=2)


def _mtime(p: Path):
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def find_pdf_sibling(pages_path: Path):
    """The PDF that corresponds to a `.pages` base. Same stem in the same folder is the only
    confident match. Falling back to "the one other PDF in this folder" is deliberate but narrow:
    a finalized application folder holds one resume, so a lone PDF beside it is that resume — but
    if there are two, guessing which is the resume is exactly the kind of silent wrong answer this
    module exists to prevent, so it returns nothing and the score goes blank."""
    exact = pages_path.with_suffix(".pdf")
    if exact.is_file():
        return exact
    try:
        pdfs = sorted(p for p in pages_path.parent.glob("*.pdf") if p.is_file())
    except OSError:
        return None
    return pdfs[0] if len(pdfs) == 1 else None


def resolve_base_artifact(source_path) -> BaseArtifact:
    """Map a resume-index path to the file the comparison pass should actually read."""
    src = Path(str(source_path).strip().strip('"').strip("'")).expanduser()
    suffix = src.suffix.lower()

    if suffix in DIRECT_READABLE:
        if not src.is_file():
            return BaseArtifact(str(src), None, None, STATUS_NOT_FOUND,
                                f"Base file does not exist: {src}")
        return BaseArtifact(str(src), str(src), DIRECT_READABLE[suffix], STATUS_OK,
                            f"Read directly via the {DIRECT_READABLE[suffix]}.")

    if suffix != ".pages":
        return BaseArtifact(str(src), None, None, STATUS_NOT_FOUND,
                            f"Unsupported resume format {suffix or '(none)'} — no reader for it.")

    if not src.is_file() and not src.is_dir():
        # A .pages bundle is a directory on some systems and a flat file on others; accept both.
        return BaseArtifact(str(src), None, None, STATUS_NOT_FOUND,
                            f"Base file does not exist: {src}. Check the path in "
                            f"02-resume-index.md — a wrong path here is usually a punctuation "
                            f"drift in the folder name, not a missing resume.")

    pdf = find_pdf_sibling(src)
    if pdf is None:
        return BaseArtifact(
            str(src), None, None, STATUS_NO_PDF,
            f"No authoritative PDF beside {src.name}. A .pages file cannot be read directly, and "
            f"the resume index's prose preview is a summary, not the document — so the base is "
            f"NOT scored. Export a PDF next to the .pages and re-run.")

    t_pages, t_pdf = _mtime(src), _mtime(pdf)
    if t_pages is not None and t_pdf is not None and t_pages - t_pdf > STALE_TOLERANCE_SECONDS:
        drift_days = (t_pages - t_pdf) / 86400.0
        return BaseArtifact(
            str(src), str(pdf), DIRECT_READABLE[".pdf"], STATUS_STALE,
            f"PDF may be STALE: {pdf.name} was exported about {drift_days:.1f} day(s) before the "
            f".pages was last edited, so it may be missing the most recent manual edits. Scored "
            f"anyway, but treat the base score as a lower bound.")

    return BaseArtifact(str(src), str(pdf), DIRECT_READABLE[".pdf"], STATUS_OK,
                        f"Authoritative PDF sibling: {pdf.name}")


def main(argv):
    ap = argparse.ArgumentParser(
        description="Resolve the readable, authoritative artifact for a resume base.")
    ap.add_argument("path", help="Base path from 02-resume-index.md (.pages/.pdf/.docx/.md/.txt)")
    a = ap.parse_args(argv[1:])
    art = resolve_base_artifact(a.path)
    print(art.to_json())
    # Nonzero when there is nothing legitimate to score, so a caller cannot mistake a failed
    # lookup for a low score.
    return 0 if art.scoreable else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
