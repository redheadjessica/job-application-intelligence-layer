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

Every base in the current setup is an Apple Pages file, which cannot be read directly — so the
comparison pass reads a PDF. The finalized-application folders follow one convention:

    <name>.pages       the editable source
    <name>.pdf         THE RESUME AS SUBMITTED — the only artifact this module returns
    <name> FULL.pdf    the same resume PLUS the cover letter, bundled for convenience

Selection is deliberately strict, because each loose rule breaks the score in a different way:

  * ONLY the exact-name resume-only PDF is authoritative. No "the single PDF in this folder"
    fallback — these folders routinely hold three or four PDFs, and picking one by elimination is
    how a cover letter ends up inside a resume score.
  * `FULL.pdf` is NEVER a fallback. These columns answer a deliberately narrow question — how much
    would changing the RESUME be worth — so cover-letter prose must not touch the number. A missing
    resume-only PDF is reported, not worked around.
  * The `.pages` file is never opened or compared. It is the editable source, not the artifact.
  * NO timestamp-based staleness. A Pages package's modification time moves for metadata, style and
    view-state changes that never touch a word of the resume, so a "stale" flag derived from it was
    mostly false positives — and a false warning attached to a real score is worse than no warning.
    (This module previously carried such a check; it was removed on 2026-07-31 after it fired on a
    Pinterest base whose PDF was in fact current.)

The one tolerance: stem matching ignores whitespace differences, so a base saved as
`"Resume - Acme .pages"` still matches `"Resume - Acme.pdf"`. That is the same name, not a guess.

    python resume_artifacts.py "/path/to/Resume - Company - Role.pages"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# Formats the comparison pass can read directly, and the tool each one needs. `.pages` is
# deliberately absent — it is the one format with no direct reader, which is the whole reason
# the PDF sibling lookup exists.
DIRECT_READABLE = {
    ".pdf": "pdf skill",
    ".md": "Read tool",
    ".txt": "Read tool",
    ".docx": "docx skill",
}

# The combined resume+cover-letter bundle. Recognized ONLY so it can be excluded by name and
# named in the error message; it is never returned.
FULL_SUFFIX_RE = re.compile(r"\s*full$", re.IGNORECASE)

# Resolution outcomes. Only `ok` carries a readable path; the rest mean BLANK scores.
STATUS_OK = "ok"
STATUS_NO_PDF = "no-readable-pdf"
STATUS_NOT_FOUND = "not-found"
SCOREABLE = (STATUS_OK,)


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


def _key(stem: str) -> str:
    """Compare stems ignoring whitespace only — `"Resume - Acme "` and `"Resume - Acme"` name the
    same document. Nothing else is normalized away."""
    return re.sub(r"\s+", "", stem).casefold()


def is_full_bundle(path) -> bool:
    """True for the `<name> FULL.pdf` resume+cover-letter bundle."""
    return bool(FULL_SUFFIX_RE.search(Path(path).stem))


def find_resume_pdf(pages_path: Path):
    """The resume-only PDF for a `.pages` base, or None.

    Exact stem match (whitespace-insensitive) and nothing else. Returning None is a normal,
    reportable outcome — never a reason to reach for a different file."""
    want = _key(pages_path.stem)
    try:
        candidates = sorted(p for p in pages_path.parent.glob("*.pdf") if p.is_file())
    except OSError:
        return None
    for p in candidates:
        if _key(p.stem) == want and not is_full_bundle(p):
            return p
    return None


def resolve_base_artifact(source_path) -> BaseArtifact:
    """Map a resume-index path to the file the comparison pass should actually read."""
    src = Path(str(source_path).strip().strip('"').strip("'")).expanduser()
    suffix = src.suffix.lower()

    if suffix in DIRECT_READABLE:
        if not src.is_file():
            return BaseArtifact(str(src), None, None, STATUS_NOT_FOUND,
                                f"Base file does not exist: {src}")
        if suffix == ".pdf" and is_full_bundle(src):
            return BaseArtifact(
                str(src), None, None, STATUS_NO_PDF,
                f"{src.name} is the combined resume+cover-letter bundle. These columns score the "
                f"RESUME only, so point at the resume-only PDF instead.")
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

    pdf = find_resume_pdf(src)
    if pdf is None:
        try:
            present = sorted(p.name for p in src.parent.glob("*.pdf"))
        except OSError:
            present = []
        seen = f" PDFs present: {', '.join(present)}." if present else " No PDFs in that folder."
        return BaseArtifact(
            str(src), None, None, STATUS_NO_PDF,
            f"No resume-only PDF named to match {src.name}.{seen} The base is NOT scored: the "
            f"combined FULL.pdf bundle would let cover-letter text influence a resume score, and "
            f"the resume index's preview is a summary, not the document. Export "
            f"'{src.with_suffix('.pdf').name}' beside the .pages and re-run.")

    return BaseArtifact(str(src), str(pdf), DIRECT_READABLE[".pdf"], STATUS_OK,
                        f"Resume-only PDF: {pdf.name}")


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
