#!/usr/bin/env python3
"""Detect duplicated resume-bullet text between the experience bank and the cold canonical files.

WHY THIS EXISTS. Approved bullets used to live in two places at once — `04-experience-bank.md` and a
`03*-canonical.md` deep-reference file. On 2026-07-20 canon corrected the Ascend opening bullet to drop
"Ascend" and "private alpha" (both already sit in the resume's section header, so repeating them wastes
the line). The canonical file was updated. The experience-bank copy was not. For eleven days the
ALWAYS-READ file served wording canon had explicitly retired, and it kept reaching real drafts.

Discipline had already been tried: the canonical file carried a dated warning saying never to
reintroduce that phrasing. It still drifted, because nothing compared the two copies.

The structural fix is one home per bullet: bullet TEXT lives only in the experience bank (which the
tailoring agent always reads, so it costs nothing extra), and canonical files hold evidence, facts,
guardrail rationale and history. This script is the guard on that rule — it finds sentences that appear
in both, which is the shape the failure takes.

    python3 check_canon_drift.py [canon_dir]

Exit 0 = clean, 1 = duplication found. Read-only; never edits anything.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEFAULT_DIR = Path(
    "PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO")
BANK = "04-experience-bank.md"
COLD_GLOB = "03*-canonical.md"

# A bullet worth comparing: long enough to be real prose, not a heading or a path.
MIN_WORDS = 8
BULLET = re.compile(r'^\s*(?:[-*+]|\d+[.)])\s+(.*)$')


def normalize(s: str) -> str:
    """Compare on substance: drop markdown emphasis, links, code ticks, and punctuation/case noise."""
    s = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', s)      # links -> label
    s = re.sub(r'[*_`>]', '', s)                         # emphasis / code / quote marks
    s = re.sub(r'<!--.*?-->', '', s, flags=re.S)         # inline comments
    s = re.sub(r'[^\w\s]', ' ', s)                       # punctuation
    return re.sub(r'\s+', ' ', s).strip().lower()


def bullets(path: Path) -> dict[str, tuple[int, str]]:
    """Normalized bullet text -> (line number, original text)."""
    found: dict[str, tuple[int, str]] = {}
    in_fence = False
    for n, raw in enumerate(path.read_text(encoding='utf-8').split('\n'), 1):
        if raw.lstrip().startswith(('```', '~~~')):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = BULLET.match(raw)
        if not m:
            continue
        text = m.group(1)
        key = normalize(text)
        if len(key.split()) >= MIN_WORDS:
            found.setdefault(key, (n, text.strip()))
    return found


def main(argv: list[str]) -> int:
    canon = Path(argv[1]) if len(argv) > 1 else DEFAULT_DIR
    bank_path = canon / BANK
    if not bank_path.is_file():
        print(f"[canon-drift] no experience bank at {bank_path} — nothing to check.")
        return 0

    bank = bullets(bank_path)
    problems = 0
    for cold_path in sorted(canon.glob(COLD_GLOB)):
        cold = bullets(cold_path)
        shared = sorted(set(bank) & set(cold))
        for key in shared:
            bank_line, bank_text = bank[key]
            cold_line, _ = cold[key]
            problems += 1
            print(f"[canon-drift] DUPLICATED BULLET\n"
                  f"  {BANK}:{bank_line}\n"
                  f"  {cold_path.name}:{cold_line}\n"
                  f"  text: {bank_text[:110]}{'…' if len(bank_text) > 110 else ''}\n")

    if problems:
        print(f"[canon-drift] {problems} bullet(s) live in two files. Bullet TEXT belongs ONLY in "
              f"{BANK}; the canonical file should reference it, not restate it. Two copies drift, and "
              f"the always-read one is the copy that ships.")
        return 1
    print(f"[canon-drift] clean — no bullet text duplicated between {BANK} and "
          f"{len(list(canon.glob(COLD_GLOB)))} canonical file(s).")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
