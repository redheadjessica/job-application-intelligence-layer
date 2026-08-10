#!/usr/bin/env python3
"""
Validate one `application_resume_output - [Company] - [Role].md` against the spec.

WHY THIS EXISTS. On 2026-08-07 a 35-résumé batch shipped with 32 files carrying no writing
links at all, 27 missing the Selected Writing section entirely, 31 built to a retired output
structure, 3 with no skills section, and bullets that had to be run through a separate tool
before they could be pasted into a résumé. Every one of those is a presence-and-shape defect
— fully machine-checkable — and every one reached the candidate because the only check was
someone reading the files. Nobody reads 35 files.

Worse: the QA pass that declared the batch clean tested for a section name the retired
structure also happened to contain, so it passed 35/35 while 31 were wrong. A hand-written
check encodes whatever the author believed at the time.

So this script does NOT hardcode the contract. It PARSES the spec's own "Primary Output
Format" block for the required sections, which is the same block the agent is told to follow.
One source, two readers. If the structure changes, the checker changes with it — the failure
mode where a checker validates a format the spec has already replaced cannot recur.

Exit code 0 = pass, 1 = failures found (printed).

Usage:
    python3 check_tailoring_output.py <application_resume_output....md> [--spec <spec.md>] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_SPEC = Path(__file__).resolve().parent / "00_job_application_agent.md"
_SPEC_CANDIDATES = ("00-job_application_agent.md", "00_job_application_agent.md")

# Headings from the retired flat structure. Their presence means the run followed the
# pre-2026-08-07 shape, which is what dropped Selected Writing and the Read Log.
RETIRED_HEADINGS = (
    "questions for the candidate",
    "strategic evidence retrieval",
    "integrity check",
)
# Deliberately short. An earlier draft also listed "application question drafts", "skills
# line" and "resume base recommendation" — but the spec still uses the first as a legitimate
# subsection name, and the others are ordinary words that appear as `###` children in
# perfectly valid files. A checker that flags valid output trains people to ignore it.

# A writing/portfolio URL. Any absolute http(s) URL counts — the rule is that a NAMED
# piece carries its link, not that the link lives on a particular domain.
URL_RE = re.compile(r"https?://[^\s)\]>]+")

MIN_SKILLS_ITEMS = 8


def find_spec(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    here = Path(__file__).resolve().parent
    for name in _SPEC_CANDIDATES:
        p = here / name
        if p.is_file():
            return p
    raise SystemExit("could not locate the tailoring spec next to this script")


def required_sections(spec_text: str) -> list[str]:
    """The `## N. Name` sections from the spec's Primary Output Format block.

    Parsed, never hardcoded — see the module docstring."""
    block = re.search(r"(?ms)^## Primary Output Format\b.*?^```\n(.*?)^```", spec_text)
    if not block:
        raise SystemExit("could not find the spec's Primary Output Format fenced block")
    out = []
    for ln in block.group(1).splitlines():
        m = re.match(r"^##\s+(\d+)\.\s+(.+)$", ln.rstrip())
        if not m:
            continue
        # The block aligns explanatory prose after the section name with runs of spaces,
        # and sometimes an em dash. Both are commentary, not part of the heading text.
        rest = m.group(2).strip()
        name = re.split(r"\s{2,}|\s+—\s+", rest)[0].strip()
        # A section the spec itself marks conditional ("ONLY if …", "omit the section
        # entirely otherwise") is not required, and flagging its absence would be the
        # checker inventing a rule the spec doesn't have.
        optional = bool(re.search(r"(?i)\bonly if\b|\bomit\b", rest))
        out.append({"name": f"{m.group(1)}. {name}", "optional": optional})
    return out


def required_children(spec_text: str, parent_num: str) -> list[str]:
    """`###` children listed under a given `## N.` section in the spec's block."""
    block = re.search(r"(?ms)^## Primary Output Format\b.*?^```\n(.*?)^```", spec_text)
    lines = block.group(1).splitlines() if block else []
    out, inside = [], False
    for ln in lines:
        if re.match(rf"^##\s+{re.escape(parent_num)}\.", ln.strip()):
            inside = True
            continue
        if re.match(r"^##\s+\d+\.", ln.strip()):
            inside = False
        if inside:
            m = re.match(r"^\s+###\s+([^\n]+?)(?:\s{2,}.*)?$", ln.rstrip())
            if m:
                out.append(m.group(1).strip())
    return out


def _norm(s: str) -> str:
    s = s.lower().replace("é", "e").replace("’", "'")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _headings(text: str) -> list[tuple[int, str]]:
    return [(len(m.group(1)), m.group(2).strip())
            for m in re.finditer(r"(?m)^(#{2,4})\s+(.+?)\s*$", text)]


def _section_body(text: str, heading_pred) -> str | None:
    """Body of the first heading matching a predicate, up to the next same-or-higher heading."""
    for m in re.finditer(r"(?m)^(#{2,4})\s+(.+?)\s*$", text):
        level, name = len(m.group(1)), m.group(2).strip()
        if not heading_pred(name):
            continue
        rest = text[m.end():]
        nxt = re.search(rf"(?m)^#{{2,{level}}}\s+", rest)
        return rest[:nxt.start()] if nxt else rest
    return None


def check(md_text: str, spec_text: str) -> list[dict]:
    fails: list[dict] = []
    def fail(rule, detail):
        fails.append({"rule": rule, "detail": detail})

    heads = _headings(md_text)
    head_norms = [_norm(h) for _, h in heads]

    # 1. every required top-level section, in order
    req = required_sections(spec_text)
    positions = []
    for r in req:
        want = _norm(r["name"])
        idx = next((i for i, h in enumerate(head_norms) if h.startswith(want)), None)
        if idx is None:
            if not r["optional"]:
                fail("missing-section", f"required section not found: '{r['name']}'")
        else:
            positions.append((idx, r["name"]))
    ordered = [r for _, r in sorted(positions)]
    if ordered != [r for _, r in positions]:
        fail("section-order", f"sections out of spec order: found {ordered}")

    # 2. §2 children, incl. Selected Writing
    for child in required_children(spec_text, "2"):
        base = _norm(child.split("(")[0])
        key = base.split(" only if")[0].split(" one ")[0].strip()
        if not any(key and key in h for h in head_norms):
            fail("missing-subsection", f"§2 child missing: '{child}'")

    # 3. retired headings
    for h in head_norms:
        for r in RETIRED_HEADINGS:
            if h.startswith(_norm(r)):
                fail("retired-heading", f"heading from the pre-08-07-26 structure: '{h}'")

    # 4. Selected Writing: every named piece carries a URL
    sw = _section_body(md_text, lambda n: "selected writing" in _norm(n))
    if sw is not None:
        named = [ln for ln in sw.splitlines()
                 if re.match(r"^\s*[-*\d.]+\s", ln) and re.search(r"[\"“][^\"”]{6,}[\"”]|\*\*[^*]{6,}\*\*", ln)]
        for ln in named:
            if not URL_RE.search(ln):
                fail("writing-piece-without-url", f"named piece with no URL: {ln.strip()[:110]}")
        if named and not URL_RE.search(sw):
            fail("selected-writing-no-urls", "Selected Writing names pieces but carries no URLs at all")

    # 5. paste-ready work-experience bullets
    we = _section_body(md_text, lambda n: _norm(n).startswith("work experience"))
    if we:
        # The per-role block is NOTES first, then the paste-ready block. The notes
        # legitimately quote and number things (`1. <label> (canonical "…") — unchanged`),
        # so scanning the whole block flags valid files. Two high-precision
        # rules instead, both aimed at what actually forces hand-editing:
        for role_blk in re.split(r"(?m)^####\s+", we)[1:]:
            lines = role_blk.splitlines()
            role = (lines[0].strip() if lines else "?")[:60]

            # (a) an annotation line sitting directly beneath a `- ` bullet — Flickr's
            #     `*(Driver: …)*` shape. Unambiguous: it breaks a contiguous paste.
            for i, ln in enumerate(lines[:-1]):
                if re.match(r"^\s*-\s+\S", ln) and re.match(
                        r"^\s*\*?\((?:driver|why|rationale|source)\b", lines[i + 1].strip(), re.I):
                    fail("bullet-annotation",
                         f"[{role}] annotation under a bullet: {lines[i + 1].strip()[:90]}")

            # (b) résumé-length bullet text delivered ONLY as numbered/quoted lines with no
            #     bare `- ` block anywhere in the role — Papa's `3. Views: "…"` shape.
            dash = [l for l in lines if re.match(r"^\s*-\s+\S", l) and len(l.strip()) > 60]
            numbered = [l for l in lines
                        if re.match(r"^\s*\d+\.\s+", l) and len(l.strip()) > 60
                        and ('"' in l or "“" in l or re.match(r"^\s*\d+\.\s+\*\*", l))]
            if numbered and not dash:
                fail("bullet-not-paste-ready",
                     f"[{role}] bullets delivered as numbered/quoted lines with no paste-ready "
                     f"`- ` block: {numbered[0].strip()[:90]}")

    # 6. skills present and substantive
    sk = _section_body(md_text, lambda n: "skills" in _norm(n))
    if sk is None:
        fail("missing-skills", "no Skills section")
    else:
        best = max((len([x for x in l.split(",") if x.strip()])
                    for l in sk.splitlines() if l.count(",") >= 3), default=0)
        if best < MIN_SKILLS_ITEMS:
            fail("skills-too-thin", f"skills line has {best} items (minimum {MIN_SKILLS_ITEMS})")

    # 7. Read Log present and last
    log_idx = next((i for i, h in enumerate(head_norms) if h.startswith("read log")), None)
    if log_idx is None:
        fail("missing-read-log", "no Read Log section (the audit trail for which canon files were read)")
    elif log_idx != len(heads) - 1:
        fail("read-log-not-last", f"Read Log is followed by: {heads[log_idx + 1][1]}")

    # 8. base ledger verdicts
    base_body = _section_body(md_text, lambda n: _norm(n) in ("base", "1 base") or _norm(n).startswith("base "))
    if base_body is not None and not re.search(r"(?i)reject|not applicable|considered", base_body):
        fail("no-base-verdicts", "§2 Base states no accept/reject verdicts for the registered bases")

    return fails


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("output_md")
    ap.add_argument("--spec", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv[1:])

    md = Path(args.output_md)
    if not md.is_file():
        raise SystemExit(f"not found: {md}")
    spec = find_spec(args.spec)
    fails = check(md.read_text(encoding="utf-8", errors="replace"),
                  spec.read_text(encoding="utf-8", errors="replace"))
    if args.json:
        print(json.dumps({"file": str(md), "pass": not fails, "failures": fails}, indent=1))
    else:
        if not fails:
            print(f"PASS  {md.name}")
        else:
            print(f"FAIL  {md.name}  ({len(fails)} issue(s))")
            for f in fails:
                print(f"   [{f['rule']}] {f['detail']}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
