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

# The skills line is the deliverable the candidate pastes whole, so it must be complete on its
# own. But how full "full" is depends on the candidate's résumé layout and term lengths, so the
# floor is CANDIDATE DATA, not an engine constant — the same reason the comp thresholds live in
# jail.config.json rather than in norm_contracts. Default 12 is a generic "not threadbare" floor;
# one candidate calibrated hers to 14 after calling a 13-item line "too short by 1" on review.
# Override with `resume.min_skills_items` in jail.config.json.
DEFAULT_MIN_SKILLS_ITEMS = 12


def _configured_min_skills() -> int:
    """`resume.min_skills_items` from the repo-root jail.config.json, else the default."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        cfg = parent / "jail.config.json"
        if cfg.is_file():
            try:
                v = (json.loads(cfg.read_text(encoding="utf-8")).get("resume") or {}).get("min_skills_items")
                if isinstance(v, int) and v > 0:
                    return v
            except Exception:
                pass
            break
    return DEFAULT_MIN_SKILLS_ITEMS


MIN_SKILLS_ITEMS = _configured_min_skills()


def skills_item_count(section_body: str) -> int:
    """Items on the actual skills LINE — not on a prose notes line that happens to contain commas.

    The first version took "the longest comma-rich line in the section", which cheerfully
    measured `- Intentionally omitted: the psychology/behavior-change cluster …` and reported
    a 13-item skills line as having 5. A checker that measures the wrong line is worse than no
    checker: it reports confident numbers about something it never looked at."""
    best = 0
    for raw in (section_body or "").splitlines():
        s = raw.strip()
        if not s or s.startswith(("#", "-", "*", ">", "|")):
            continue          # notes bullets, headings, tables
        if s.startswith("**") or re.match(r"^[A-Z][^,]{0,40}:\s", s):
            continue          # a bolded lead-in or a "Notes:"-style label, not the line
        if s.count(",") < 3:
            continue
        # A real skills line is a list, not prose: sentence-ending periods disqualify it.
        if re.search(r"\.\s+[A-Z]", s) or s.endswith("."):
            continue
        best = max(best, len([x for x in s.split(",") if x.strip()]))
    return best


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


RESUME_EXTS = (".pages", ".docx", ".pdf", ".doc", ".rtf", ".odt")


def check_job_folder(folder: Path) -> list[dict]:
    """Folder-level rules — the ones that cannot be seen from the .md alone.

    Exactly ONE base résumé artifact belongs in a job folder. On 08-07-26 four folders got
    both a `.pages` and a `.pdf` of the same résumé, and three got a PDF with no editable
    source — agents copying the PDF so they could score it, which was never necessary
    (the comparison pass reads the base's PDF in place, from the base's own folder)."""
    fails: list[dict] = []
    if not folder.is_dir():
        return fails
    # Résumé artifacts only: cover letters and the job capture are not base copies.
    arts = [p for p in sorted(folder.iterdir())
            if p.suffix.lower() in RESUME_EXTS
            and "resume" in p.name.lower()
            and "coverletter" not in p.name.lower().replace("-", "").replace(" ", "")
            and "cover-letter" not in p.name.lower()]
    stems: dict[str, list[Path]] = {}
    for p in arts:
        stems.setdefault(re.sub(r"\s+", " ", p.stem).strip().lower(), []).append(p)
    for stem, group in stems.items():
        if len(group) > 1:
            names = ", ".join(p.name for p in group)
            fails.append({"rule": "duplicate-base-artifact",
                          "detail": f"the same résumé copied in more than one format: {names}. "
                                    f"Copy exactly one base file, in its native format."})
    if arts and all(p.suffix.lower() == ".pdf" for p in arts):
        fails.append({"rule": "no-editable-base",
                      "detail": f"only a PDF was copied ({arts[0].name}) — if the base has an "
                                f"editable source (.pages/.docx), that is what belongs here; "
                                f"a PDF leaves nothing to tailor from."})
    return fails


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
        best = skills_item_count(sk)
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
    fails += check_job_folder(md.parent)
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
