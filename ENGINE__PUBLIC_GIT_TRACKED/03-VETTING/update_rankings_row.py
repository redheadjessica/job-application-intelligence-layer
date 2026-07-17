#!/usr/bin/env python3
"""Write a tailor/cover-letter result BACK into a batch's rankings CSV + XLSX.

Why this exists: vet-jobs.js writes "Base Resume Used" as a blank at vet time with the comment
"filled later by the tailor step" — but nothing ever filled it. The tailor agent already returns
`recommended_base`; it was simply discarded. The column was therefore empty in every batch ever
produced, and had to be reconstructed by hand from the per-job `application_resume_output*.md`
files. Same story for "Cover Letter?" — there was no way to see which jobs had a letter written.

This closes that handoff. Both the tailor step and the cover-letter step call it per job.

Matching: by canonical URL first, then job-file name. URL is primary because the same posting is
often re-fetched under different filenames across batches (e.g. Everyday Health exists as
`...__pm.txt` and `...__everyday-health.txt`; Google as `google__...` and `product-manager-...`)
— all of which resolve to one canonical URL via prep_common.normalize_url.

Both CSV and XLSX are edited IN PLACE (never regenerated) so the user's own manual edits,
formatting, and column renames survive.

    python update_rankings_row.py --batch "<batch dir>" --job-file "airtable__product-manager.txt" \
        [--url "https://..."] [--base "Anthropic — PM, Consumer (6/25/26)"] [--cover-letter]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "02-PREP"))
try:
    from prep_common import normalize_url
except Exception:  # prep deps unavailable — fall back to exact string compare
    def normalize_url(u):
        return (u or "").strip().lower().rstrip("/")

# Column headers are matched by PREFIX, not equality: users rename them locally (Jessica's reads
# "Base Resume Used - Jess-Requested Custom Field"). Prefix-matching keeps that working.
H_BASE_PREFIX = "base resume used"
H_COVER_PREFIX = "cover letter"
H_JOBFILE = "job file"
H_TITLE_PREFIX = "job post title"

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# A base name terminates at its parenthesized date; everything after is prose the agent added
# ("...chassis, merged with", "...adapted significantly", "...copied and renamed to X.pages").
_DATE_END = re.compile(r'^(.*?\((?:\d{1,2}/\d{1,2}/\d{2}|\d{1,2}/\d{2}|[A-Z][a-z]{2,8}\s+\d{4})\))')
_PROSE_CUT = re.compile(
    r'(?:,\s*(?:adapted|merged|chassis|retitled|copied|from the)|\.\s|\s+chassis\b|\s+—\s*see\b)', re.I)
# A leading label, in case a caller passes a whole markdown line rather than the bare value.
_LABEL = re.compile(r'^\s*(?:primary|chosen|recommended|selected)\s+base\s*(?:\(merge\))?\s*:\s*|'
                    r'^\s*base\s+(?:chosen|used|actually used)\s*:\s*', re.I)


def terse_base(s: str) -> str:
    """Normalize a verbose agent-returned base into the tracker's terse house style.

    'Anthropic — PM, Consumer (6/25/26), copied and renamed to Jessica-Barnett-Resume - ....pages'
        -> 'Anthropic — PM, Consumer (6/25/26)'
    'Dropbox Principal PM — Teams & Collab (Jan 2026)'  -> 'Dropbox Principal PM — Teams & Collab (1/26)'
    """
    s = re.sub(r'\*\*', '', (s or "").strip())
    s = re.sub(r'^\s*[-*•]\s+', '', s)   # leading markdown bullet
    s = _LABEL.sub('', s).strip()
    m = _DATE_END.match(s)
    s = m.group(1) if m else _PROSE_CUT.split(s, maxsplit=1)[0]
    s = s.strip().rstrip('.,').strip()

    def _d(mm):
        mon = mm.group(1).lower()[:3]
        return f"({MONTHS[mon]}/{mm.group(2)[-2:]})" if mon in MONTHS else mm.group(0)

    s = re.sub(r'\(([A-Z][a-z]{2,8})\s+(\d{4})\)', _d, s)
    return s.replace("Professional Services", "Prof. Services")


def _col(headers, prefix):
    for i, h in enumerate(headers):
        if (h or "").strip().lower().startswith(prefix):
            return i
    return None


def _url_from_title(cell_value: str):
    m = re.search(r'https?://\S+', str(cell_value or ""))
    return m.group(0) if m else None


def _is_match(row_jobfile, row_title, job_file, url):
    if url:
        row_url = _url_from_title(row_title)
        if row_url and normalize_url(row_url) == normalize_url(url):
            return True
    return bool(job_file) and (row_jobfile or "").strip() == job_file.strip()


def update_csv(path: Path, job_file, url, base, cover_letter) -> bool:
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    if not rows:
        return False
    headers = rows[0]
    ci_base, ci_cl = _col(headers, H_BASE_PREFIX), _col(headers, H_COVER_PREFIX)
    ci_jf, ci_title = _col(headers, H_JOBFILE), _col(headers, H_TITLE_PREFIX)

    if cover_letter and ci_cl is None:  # older batch predates the column — append it
        headers.append("Cover Letter?")
        ci_cl = len(headers) - 1
        for r in rows[1:]:
            r.extend([""] * (len(headers) - len(r)))

    hit = False
    for r in rows[1:]:
        if len(r) < len(headers):
            r.extend([""] * (len(headers) - len(r)))
        jf = r[ci_jf] if ci_jf is not None and ci_jf < len(r) else ""
        ti = r[ci_title] if ci_title is not None and ci_title < len(r) else ""
        if not _is_match(jf, ti, job_file, url):
            continue
        hit = True
        if base and ci_base is not None:
            r[ci_base] = base
        if cover_letter and ci_cl is not None:
            r[ci_cl] = "Y"
    if hit:
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
    return hit


def update_xlsx(path: Path, job_file, url, base, cover_letter) -> bool:
    try:
        from openpyxl import load_workbook
    except ImportError:
        return False
    wb = load_workbook(path)
    ws = wb.active
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    ci_base, ci_cl = _col(headers, H_BASE_PREFIX), _col(headers, H_COVER_PREFIX)
    ci_jf, ci_title = _col(headers, H_JOBFILE), _col(headers, H_TITLE_PREFIX)

    if cover_letter and ci_cl is None:
        ci_cl = len(headers)
        ws.cell(1, ci_cl + 1, "Cover Letter?")

    hit = False
    for r in range(2, ws.max_row + 1):
        jf = ws.cell(r, ci_jf + 1).value if ci_jf is not None else ""
        tcell = ws.cell(r, ci_title + 1) if ci_title is not None else None
        # Prefer the real hyperlink target over the display text.
        ti = ""
        if tcell is not None:
            ti = (tcell.hyperlink.target if tcell.hyperlink and tcell.hyperlink.target
                  else str(tcell.value or ""))
        if not _is_match(jf, ti, job_file, url):
            continue
        hit = True
        if base and ci_base is not None:
            ws.cell(r, ci_base + 1, base)
        if cover_letter and ci_cl is not None:
            ws.cell(r, ci_cl + 1, "Y")
    if hit:
        wb.save(path)
    return hit


def main(argv):
    ap = argparse.ArgumentParser(description="Write a tailor/cover-letter result back into the rankings.")
    ap.add_argument("--batch", required=True, help="Batch root, e.g. __READY_TO_REVIEW__PRIVATE_GITIGNORED/07-16-26")
    ap.add_argument("--job-file", default=None, help="Job .txt filename (fallback match key)")
    ap.add_argument("--url", default=None, help="Canonical job URL (primary match key)")
    ap.add_argument("--base", default=None, help="Resume base used (normalized to house style)")
    ap.add_argument("--cover-letter", action="store_true", help="Mark this row's Cover Letter? as Y")
    a = ap.parse_args(argv[1:])

    if not a.base and not a.cover_letter:
        raise SystemExit("Nothing to write: pass --base and/or --cover-letter.")
    if not a.job_file and not a.url:
        raise SystemExit("Need at least one match key: --job-file and/or --url.")

    rankings = Path(a.batch) / "1 - Rankings"
    if not rankings.is_dir():
        print(f"note: no '1 - Rankings/' in {a.batch} — nothing to update.")
        return 0

    base = terse_base(a.base) if a.base else None
    touched = []
    for p in sorted(rankings.glob("*-rankings.csv")):
        if update_csv(p, a.job_file, a.url, base, a.cover_letter):
            touched.append(p.name)
    for p in sorted(rankings.glob("*-rankings.xlsx")):
        if p.name.startswith("~$"):
            continue  # Excel lock file
        if update_xlsx(p, a.job_file, a.url, base, a.cover_letter):
            touched.append(p.name)

    key = a.url or a.job_file
    if touched:
        bits = []
        if base:
            bits.append(f'base="{base}"')
        if a.cover_letter:
            bits.append("cover_letter=Y")
        print(f"Updated {', '.join(touched)} for {key}: {' '.join(bits)}")
    else:
        # Loud, not silent — a miss here is exactly how the column silently stayed empty before.
        print(f"WARNING: no rankings row matched {key} — '{rankings}' left unchanged. "
              f"The row may live in a different batch, or the job file/URL may not match.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
