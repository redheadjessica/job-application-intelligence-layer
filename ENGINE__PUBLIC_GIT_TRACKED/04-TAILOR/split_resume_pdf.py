#!/usr/bin/env python3
"""Split a freshly-exported 3-page résumé+cover-letter PDF into the three canonical artifacts.

The candidate exports one PDF from Pages: pages 1-2 = résumé, page 3 = cover letter. This produces,
in the SAME folder, the exact naming `resume_artifacts.py` expects:

    <name> FULL.pdf   the full 3-page bundle (résumé + cover letter)
    <name>.pdf        RÉSUMÉ ONLY (pages 1-2) — the exact-name artifact the resume scorer resolves
    <coverletter>.pdf COVER LETTER ONLY (page 3) — "Resume" in the name replaced with "CoverLetter"

Fixed layout by the candidate's choice: pages 1-2 = résumé, page 3 = cover letter. Guards HARD on a
non-3-page input so a mis-export is caught, never silently mis-split. Does NOT submit or upload
anything — file creation only.

Usage:
    python split_resume_pdf.py "/path/to/Jessica-Barnett-Resume - Company - Role.pdf"

You may point it at either the plain export or the already-renamed `… FULL.pdf`; a trailing " FULL"
is stripped to derive the base name either way.
"""
from __future__ import annotations

import os
import re
import sys

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    sys.exit("pypdf is required (pip install pypdf, or use the repo .venv).")

RESUME_PAGES = (0, 1)   # pages 1-2 (0-indexed)
COVER_PAGE = 2          # page 3


def _write_pages(reader: PdfReader, indices, dest: str) -> None:
    w = PdfWriter()
    for i in indices:
        w.add_page(reader.pages[i])
    tmp = dest + ".tmp"
    with open(tmp, "wb") as fh:
        w.write(fh)
    os.replace(tmp, dest)


def main(argv) -> int:
    if len(argv) < 2:
        sys.exit("usage: split_resume_pdf.py <exported 3-page pdf>")
    src = os.path.abspath(argv[1])
    if not os.path.isfile(src):
        sys.exit(f"not found: {src}")
    if not src.lower().endswith(".pdf"):
        sys.exit(f"not a .pdf: {src}")

    folder = os.path.dirname(src)
    stem = os.path.splitext(os.path.basename(src))[0]
    # Accept either the plain export or the already-renamed "… FULL.pdf".
    base_stem = re.sub(r"\s+FULL$", "", stem, flags=re.IGNORECASE)

    if not re.search(r"resume", base_stem, flags=re.IGNORECASE):
        sys.exit(f"filename has no 'Resume' token to swap for the cover-letter name: {base_stem!r}")

    # Read + HARD guard on page count (the candidate's layout is exactly 3 pages).
    reader = PdfReader(src)
    n = len(reader.pages)
    if n != 3:
        sys.exit(f"expected exactly 3 pages (2 résumé + 1 cover letter), found {n}. "
                 f"Re-export or split manually — refusing to guess the split.")

    full_path = os.path.join(folder, f"{base_stem} FULL.pdf")
    resume_path = os.path.join(folder, f"{base_stem}.pdf")
    cover_stem = re.sub(r"resume", "CoverLetter", base_stem, count=1, flags=re.IGNORECASE)
    cover_path = os.path.join(folder, f"{cover_stem}.pdf")

    # 1) the FULL bundle (all 3 pages) — write it first so nothing is lost when we overwrite the base.
    _write_pages(reader, range(n), full_path)
    # 2) résumé-only (pages 1-2) at the exact base name.
    _write_pages(reader, RESUME_PAGES, resume_path)
    # 3) cover-letter-only (page 3).
    _write_pages(reader, (COVER_PAGE,), cover_path)

    print("Created 3 artifacts:")
    for tag, p in (("bundle (3pp)", full_path), ("résumé-only (pp1-2)", resume_path),
                   ("cover letter (p3)", cover_path)):
        print(f"  [{tag:<20}] {p}")
    print("\nNOTE: attaching these to a job posting / submitting is NOT done here — that's your step.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
