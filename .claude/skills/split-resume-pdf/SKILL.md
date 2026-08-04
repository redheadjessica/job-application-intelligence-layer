---
name: split-resume-pdf
description: Split a freshly-exported 3-page résumé+cover-letter PDF (pages 1-2 = résumé, page 3 = cover letter) into the three canonical artifacts the pipeline expects — the full bundle (`<name> FULL.pdf`), the résumé-only PDF (`<name>.pdf`, the exact-name artifact the resume scorer resolves), and the cover-letter-only PDF (`<name>` with "Resume" swapped to "CoverLetter"). File creation only — NEVER attaches to a job posting or submits anything. Run only on the user's explicit instruction, pointed at a specific exported PDF.
---

# Split an exported résumé+cover-letter PDF into its 3 canonical files

The user exports ONE PDF from Pages containing **pages 1-2 = résumé, page 3 = cover letter**. This skill turns that single export into the three files the rest of the system (and the user's application uploads) expect, with the exact naming `ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/resume_artifacts.py` resolves:

- `<name> FULL.pdf` — the full 3-page bundle (résumé + cover letter)
- `<name>.pdf` — **résumé only** (pages 1-2) — the authoritative exact-name artifact the résumé-comparison scorer reads
- `<name>` with "Resume" → "CoverLetter" `.pdf` — **cover letter only** (page 3)

## Scope boundary (hard)

This does **file creation only**. It does NOT attach files to a job posting, fill an application form, or submit anything — uploading to a posting is the user's own step, and the pipeline never submits. Say this plainly if the user asks it to "apply" or "attach."

## When to run

Only on the user's explicit instruction — e.g. "split the resume PDF for `<path>`", "I exported the Acme resume, split it", "/split-resume-pdf `<path>`". Do not run it speculatively.

## Step 1 — Get the exported PDF path

The user hands you the path to the just-exported PDF (usually in their Dropbox résumé folder). The filename must contain "Resume" (so the cover-letter name can be derived) and the file must be exactly 3 pages. You may point the tool at either the plain export or an already-renamed `… FULL.pdf`; a trailing " FULL" is stripped to derive the base name. If the user names a folder instead of a file, list the candidate PDFs and ask which one (do not guess).

## Step 2 — Run the splitter

```bash
PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"; "$PY" ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/split_resume_pdf.py "<path to exported 3-page PDF>"
```

It writes all three files into the same folder as the input and prints their paths + page counts. It **fails closed** (refuses, no files written) if the input is not exactly 3 pages or has no "Resume" token — so a mis-export is caught rather than silently mis-split. If it fails, report the exact message and ask the user to re-export or confirm the page layout; do not try to force a split.

## Step 3 — Report

Tell the user the three files created (résumé-only, cover-letter-only, full bundle) with their paths, and remind them the final attach-to-the-posting step is theirs.
