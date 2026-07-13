#!/usr/bin/env python3
"""Scaffold a fresh review batch under __READY TO REVIEW/<MM-DD-YY>/.

Every file a run produces lands inside that one dated folder:

    __READY TO REVIEW/<batch>/
      0 - Prep Report/                   <- prep-report.md + prep-manifest.json
      1 - Rankings/                      <- vet-jobs writes the CSV/MD/XLSX here
      2 - Tailored Resumes/              <- one folder per tailored job
      3 - Source Material/
        All Job Posts (full text)/       <- USABLE job posts (ranking reads here)
        Needs Review/                    <- thin/questionable fetches (quarantined)
        Failed/                          <- failed-fetch stubs
        Submitted URLs - <batch>.txt     <- snapshot of the inbox URLs

Run this FIRST, then fetch into the source folder, then run the vetting front door.
It prints the exact next commands to copy-paste.

    python ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/new_batch.py            # uses today's date
    python ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/new_batch.py 06-04-26   # explicit MM-DD-YY
"""
from __future__ import annotations

import re
import shutil
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_SUBPATH = "3 - Source Material/All Job Posts (full text)"
TIERS = (
    "0 - Prep Report",
    "1 - Rankings",
    "2 - Tailored Resumes",
    "3 - Source Material",
    SRC_SUBPATH,
    "3 - Source Material/Needs Review",
    "3 - Source Material/Failed",
)


def resolve_batch(arg: str | None) -> str:
    if not arg:
        return date.today().strftime("%m-%d-%y")
    if not re.fullmatch(r"\d{2}-\d{2}-\d{2}", arg):
        raise SystemExit(f"Batch date must be MM-DD-YY (e.g. 06-04-26), got: {arg!r}")
    return arg


def main() -> None:
    batch = resolve_batch(sys.argv[1] if len(sys.argv) > 1 else None)
    review_root = REPO_ROOT / "__READY TO REVIEW" / batch

    if review_root.exists():
        print(f"Note: {review_root} already exists — ensuring the tier folders are present.")
    for tier in TIERS:
        (review_root / tier).mkdir(parents=True, exist_ok=True)

    # Snapshot tonight's URLs from the inbox into the batch (don't clobber an existing snapshot).
    # The public template lives under ENGINE; your private working copy lives under PRIVATE
    # (gitignored). Create the working copy from the template on first run.
    inbox = REPO_ROOT / "PRIVATE__YOUR_FILES_GITIGNORED" / "01-INBOX__YOUR_PRIVATE_INFO" / "paste-job-urls-to-rank-here.txt"
    inbox_template = REPO_ROOT / "ENGINE__PUBLIC_GIT_TRACKED" / "01-INBOX" / "paste-job-urls-to-rank-here.template.txt"
    if not inbox.exists() and inbox_template.exists():
        inbox.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(inbox_template, inbox)
        print(f"Created your private inbox working copy: {inbox.relative_to(REPO_ROOT)} — paste URLs there.")
    urls_dest = review_root / "3 - Source Material" / f"Submitted URLs - {batch}.txt"
    if urls_dest.exists():
        print(f"Note: {urls_dest.name} already present — left as-is.")
    elif inbox.exists():
        shutil.copy2(inbox, urls_dest)
        print(f"Copied inbox URLs -> {urls_dest.relative_to(REPO_ROOT)}")
    else:
        print(f"Warning: {inbox} not found — create {urls_dest.relative_to(REPO_ROOT)} manually before fetching.")

    src = review_root / SRC_SUBPATH
    print(f"\nScaffolded: {review_root.relative_to(REPO_ROOT)}/")
    for tier in TIERS:
        print(f"  {tier}/")

    # Print the exact next steps with correctly-quoted, repo-relative paths.
    src_rel = src.relative_to(REPO_ROOT)
    urls_rel = urls_dest.relative_to(REPO_ROOT)
    print("\nNext steps (run from the repo root):")
    print("  # 1) Fetch the job posts (dedupes, quarantines thin/failed, writes a prep report):")
    print(f'  .venv/bin/python3 02-PREP/prep_job_urls.py "{src_rel}" --input "{urls_rel}"')
    print('  #    then read "0 - Prep Report/prep-report.md" for a plain-English summary.')
    print('  #    Re-run the same command anytime to retry thin/failed posts (usable ones are skipped).')
    print("  # 2) Vet + tailor the top 3:")
    print(f'  run-batch {{folder: "__READY TO REVIEW/{batch}", tailor: true, topN: 3}}')
    print("\n  (Advanced) For stubborn JS-rendered pages that came back thin, retry with the renderer:")
    print(f'  .venv/bin/python3 02-PREP/prep_job_urls_playwright.py "{src_rel}" --input "{urls_rel}"')


if __name__ == "__main__":
    main()
