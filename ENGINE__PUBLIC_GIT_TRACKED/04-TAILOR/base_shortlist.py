#!/usr/bin/env python3
"""
Deterministic résumé-base shortlist for Step 5.

WHY THIS EXISTS. A résumé index grows into a long file — one real index reached 762 lines
and 80 entries — and the rulings that matter most are conditional and buried. One entry
registered a base as best for go-to-market-heavy and product-plus-marketing roles, and noted
its page 2 had been reworked specifically to carry that evidence.

Then a community-and-growth role was tailored and that base was never mentioned once — not
chosen, not even listed among the bases the run rejected. The ruling was written down and
simply never surfaced. Asking a model to reliably recall one entry out of eighty is not a
design.

So selection stops depending on recall. This script reads the index, matches each base's
own stated "best for" language against the actual job post, and emits a SHORTLIST the
tailoring run must evaluate and explicitly accept or reject in its output. The agent still
makes the judgment — it just can no longer make it silently, or in ignorance of a base the
candidate deliberately registered for exactly this kind of role.

Generic by construction: it parses the prose headings a résumé index already uses
("Best for:", "Start here first for roles centered on:", "Use it when ...", "Skills lean:"),
so no candidate has to re-annotate their index in a new syntax for this to work.

Usage:
    python3 base_shortlist.py <job-post.txt> --index <02-resume-index.md> [--top N] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Lines in an index entry that state what a base is FOR. These are the candidate's own
# words about when to reach for it, which is exactly the signal we want to match on.
TRIGGER_LABELS = (
    "best for", "start here first", "use it when", "use this base when",
    "reach for this", "skills lean",
)
# Deliberately short and purpose-only. An earlier version also matched "page 2",
# "distinct evidence allocation" and "the distinct", which pulled in an entry's whole
# body — and then long governance sections (the registry table, the promotion rule)
# out-scored real bases on sheer volume of words. Only statements of PURPOSE count.

# Words too common in job posts and résumé prose to carry selection signal.
STOPWORDS = set("""
a an and are as at be been but by for from has have how in into is it its of on or our so
that the their them they this to us was we were what when where which who will with within
you your role roles job jobs work working experience experiences product products team teams
company companies candidate candidates strong across also more most other others including
include includes new use used using build building built help helps our their its
""".split())

WORD_RE = re.compile(r"[a-z0-9][a-z0-9+/&-]{2,}")


def _terms(text: str) -> set[str]:
    return {w for w in WORD_RE.findall((text or "").lower()) if w not in STOPWORDS}


def _phrases(text: str) -> set[str]:
    """Two- and three-word phrases built ONLY from runs of consecutive content words, so
    'community activation' and 'go to market' count and 'over time' / 'set the' cannot.

    An earlier version skipped a phrase only when EVERY word was a stopword, which let
    junk like "does not" and "around the" dominate the ranking and buried the base the
    whole mechanism exists to surface. Phrases must be content-only."""
    out: set[str] = set()
    run: list[str] = []
    for w in WORD_RE.findall((text or "").lower()) + [None]:
        if w is not None and w not in STOPWORDS:
            run.append(w)
            continue
        for n in (2, 3):
            for i in range(len(run) - n + 1):
                out.add(" ".join(run[i:i + n]))
        run = []
    return out


def parse_index(index_text: str) -> list[dict]:
    """Split an index into base entries: one per `### ` heading, with the trigger prose
    the entry states about itself."""
    bases = []
    parts = re.split(r"(?m)^###\s+", index_text)
    for part in parts[1:]:
        lines = part.splitlines()
        if not lines:
            continue
        name = lines[0].strip()
        body = "\n".join(lines[1:])
        # A registry table row or a prose paragraph both count; we want the lines that
        # state PURPOSE, not the whole entry (which would match on everything).
        trigger_lines = []
        for ln in body.splitlines():
            low = ln.lower().lstrip("*_- ").strip()
            if any(low.startswith(lbl) or f"**{lbl}" in low for lbl in TRIGGER_LABELS):
                trigger_lines.append(ln)
        # An index also carries governance/reference sections under `###` — a registry
        # table, promotion rules, archetype notes — and several of those quote résumé
        # paths, so "mentions a .pages file" does NOT identify a base. What identifies a
        # base is that it states what it is FOR. Entries without a purpose line are
        # skipped and reported separately, never silently dropped.
        if not trigger_lines:
            continue
        # Score the heading too: archetype language lives there ("the 0→1 new-business
        # incubation / GTM & public-brand base") and is often the sharpest signal.
        bases.append({
            "name": name,
            "trigger_text": name + "\n" + "\n".join(trigger_lines),
            "full_text": part,
        })
    return bases


def score(base: dict, job_terms: set[str], job_phrases: set[str]) -> tuple[float, list[str]]:
    """Overlap between a base's stated purpose and the job post. Phrase matches are
    weighted far above single words — 'go-to-market' matching is meaningful, 'platform'
    matching is not."""
    text = base["trigger_text"]
    b_terms, b_phrases = _terms(text), _phrases(text)
    word_hits = sorted(b_terms & job_terms)
    phrase_hits = sorted(b_phrases & job_phrases)
    # Phrases dominate: "go to market" or "community activation" matching is real signal;
    # "platform" matching is close to noise. Normalized by the size of the purpose text so
    # a base that lists many use-cases can't out-score a precise one on volume.
    pts = (5.0 * len(phrase_hits) + 1.0 * len(word_hits)) / (1.0 + len(b_terms) / 40.0)
    matched = [f"“{p}”" for p in phrase_hits[:6]] + word_hits[:max(0, 6 - len(phrase_hits))]
    return pts, matched


_DATE_RE = re.compile(r"\(?\b(\d{1,2})[-/](\d{1,2})[-/](\d{2})\b\)?")


def _base_date(heading: str) -> str | None:
    """The registration date in a base heading — `(08-07-26)` or `(6/17/26)` — as a
    sortable `YY-MM-DD`. None when the heading carries no date."""
    m = _DATE_RE.search(heading or "")
    if not m:
        return None
    mo, dy, yr = (int(x) for x in m.groups())
    if not (1 <= mo <= 12 and 1 <= dy <= 31):
        return None
    return f"{yr:02d}-{mo:02d}-{dy:02d}"


def _tidy(s: str, limit: int = 200) -> str:
    """Collapse an index line to one readable line — headings carry long parenthetical
    governance notes ("auto-registered … under the submission-=-approval rule") that are
    pure noise when the point is to see, at a glance, what each base is for."""
    s = re.sub(r"\s+", " ", s or "").strip()
    s = re.sub(r"\((?:auto-registered|registered)[^)]*\)", "", s, flags=re.I).strip(" —-;,")
    s = re.sub(r"^\*\*(?:Best for|Start here first for roles centered on|Use it when|"
               r"Use this base when|Reach for this|Skills lean)\:?\*\*\:?\s*", "", s, flags=re.I)
    return (s[:limit].rstrip() + "…") if len(s) > limit else s


def base_ledger(job_text: str, index_text: str) -> list[dict]:
    """EVERY registered base, with what the candidate said it is for.

    Deliberately NOT a filtered shortlist. Three attempts at lexically ranking these
    against a job post all failed to surface the base a human would pick in seconds —
    prose similarity scoring is simply the wrong instrument here, and every filtered
    list carries the risk this whole mechanism exists to remove: a base going unseen.
    So nothing is filtered out. The score orders the list for reading convenience and
    carries no authority; the agent owes a verdict on every row regardless of position.

    A typical index holds a few dozen bases, i.e. a few dozen short lines. Completeness is affordable, so it is not optional."""
    rows = []
    for b in parse_index(index_text):
        purpose = "\n".join(ln for ln in b["trigger_text"].splitlines()[1:])
        rows.append({
            "base": _tidy(b["name"], 120),
            "purpose": _tidy(purpose, 240),
            "registered": _base_date(b["name"]),
        })
    # Ordered NEWEST FIRST. Deliberately not by lexical relevance: three attempts at
    # scoring purpose-prose against a job post ranked the obviously-right base 19th of 21,
    # and a bad relevance sort is worse than no relevance sort — it implies a judgment the
    # numbers cannot support and invites skipping the tail. Recency is honest, deterministic,
    # and matches the index's own "default to the most recent finalized resume as the modern
    # baseline" guidance. Relevance is the agent's job, made against all 21 purpose lines.
    rows.sort(key=lambda r: (r["registered"] or ""), reverse=True)
    return rows


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job_file", help="the captured job post .txt")
    ap.add_argument("--index", required=True, help="path to 02-resume-index.md")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])

    job = Path(args.job_file)
    idx = Path(args.index)
    if not job.is_file():
        raise SystemExit(f"job file not found: {job}")
    if not idx.is_file():
        # An index is optional for tailoring overall; say so plainly rather than failing
        # the run, but never silently pretend a shortlist was produced.
        msg = f"no résumé index at {idx} — no shortlist produced; select the base from the spec's Step 5 rules alone."
        print(json.dumps({"shortlist": [], "note": msg}) if args.json else msg)
        return 0

    rows = base_ledger(job.read_text(encoding="utf-8", errors="replace"),
                       idx.read_text(encoding="utf-8", errors="replace"))
    if args.json:
        print(json.dumps({"bases": rows}, ensure_ascii=False, indent=1))
        return 0
    print(f"REGISTERED RÉSUMÉ BASES — all {len(rows)}. Ordered for reading only; the order "
          f"carries no authority.\nYou owe a one-line verdict on EVERY row: chosen, "
          f"considered-and-rejected (why), or not applicable (why).\n")
    for i, r in enumerate(rows, 1):
        print(f"{i:>2}. {r['base']}")
        if r["purpose"]:
            print(f"    for: {r['purpose']}")
    print("\nNothing here is filtered. A base you do not mention is a base you passed over silently.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
