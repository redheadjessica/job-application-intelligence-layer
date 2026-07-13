#!/usr/bin/env python3
"""Deterministic cover-letter lint — the mechanical gate that runs BEFORE any LLM evaluation.

Enforces the mechanical rules from the voice spec (banned phrases, punctuation, link technique,
AI fingerprints). Zero tokens, never forgets a rule.

Usage (from the repo root):
  .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/cover-letter/lint_cover_letter.py path/to/letter.md
  .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/cover-letter/lint_cover_letter.py letter.md --prev path/to/previous_draft.md
  .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/cover-letter/lint_cover_letter.py letter.md --json

--prev enables PRESERVATION MODE (anti-smoothing): compares the new draft against the previous
one and errors if energy/voice was stripped (lost exclamation points, removed links, collapsed
sentence-length variance).

Personal knobs come from config.json next to this script (gitignored instance; copy
config.template.json and fill it, or let /cover-letter-intake do it): the candidate's
signature name, link-count expectations, word-count targets, disabled rule groups, and extra
banned phrases. Without a config the lint runs with the shipped defaults.

Exit codes: 0 = clean (warnings allowed), 1 = errors found, 2 = usage/IO problem.

Only stdlib. Markdown-aware: link URLs and the annotation header of exemplar files are not linted.
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

# ---------------------------------------------------------------- config

DEFAULT_CONFIG = {
    "signature_name": None,          # stripped from the body before word counts
    "lint": {
        "links": {"min": 1, "max": 5},          # min 0 = links optional
        # warn outside min/max; target_* is the range quoted in the warning message
        "body_words": {"min": 240, "max": 650, "target_min": 350, "target_max": 620},
        "disabled_rules": [],        # rule ids: em-dash, semicolon, phrase, contraction,
                                     # triads, links, link-anchor, energy, rhythm, length
        "extra_banned_phrases": [],  # [{"pattern": regex, "message": str, "level": "error"|"warn"}]
    },
}


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if path and Path(path).is_file():
        try:
            user = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"cannot read config {path}: {e}", file=sys.stderr)
            sys.exit(2)
        cfg["signature_name"] = user.get("signature_name", cfg["signature_name"])
        lint_user = user.get("lint", {})
        for key in ("links", "body_words"):
            cfg["lint"][key].update(lint_user.get(key, {}))
        for key in ("disabled_rules", "extra_banned_phrases"):
            cfg["lint"][key] = lint_user.get(key, cfg["lint"][key])
    return cfg


# ---------------------------------------------------------------- text prep

MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def load_text(path):
    raw = Path(path).read_text(encoding="utf-8")
    return raw


def prose_of(raw):
    """Return (prose, links). Prose = body text with markdown link targets stripped
    (anchor text kept), so URLs never trigger word rules."""
    links = [(m.group(1), m.group(2)) for m in MD_LINK.finditer(raw)]
    prose = MD_LINK.sub(r"\1", raw)
    # bare URLs out of prose scanning too
    prose = re.sub(r"https?://\S+", " ", prose)
    return prose, links


def sentences_of(prose):
    # crude but consistent: split on ., !, ? followed by space/EOL
    parts = re.split(r"(?<=[.!?])\s+", prose)
    out = []
    for p in parts:
        words = re.findall(r"[A-Za-z''\-]+", p)
        if len(words) >= 3:
            out.append((p.strip(), len(words)))
    return out


# ---------------------------------------------------------------- rules

# (pattern, message, level) — level: "error" | "warn"
# Patterns are case-insensitive regexes run against prose (link URLs already stripped).
# These are the generic AI-tell rules — statistical fingerprints of machine-written letters,
# not any one person's taste. Personal additions go in config.json extra_banned_phrases.
PHRASE_RULES = [
    # --- banned openers / closers ---
    (r"\bexcited to apply\b", 'Banned opener family: "excited to apply" — open with the actual point', "error"),
    (r"\bthrilled to apply\b", 'Banned opener family: "thrilled to apply"', "error"),
    (r"\bwriting to express\b", 'Banned opener: "I am writing to express..."', "error"),
    (r"\bto whom it may concern\b", '"To Whom It May Concern" — address the team or a named person', "error"),
    (r"\bthank you for (your|the) (time and )?consideration\b", 'Banned closer: "thank you for your consideration"', "error"),
    (r"\bthank you for considering\b", 'Banned closer family: "thank you for considering..."', "error"),
    (r"\bi would welcome the opportunity\b", 'Banned closer: "I would welcome the opportunity..."', "error"),
    (r"\bconfident (that )?my skills and experience\b", "Stock closer: confident-my-skills-make-me-ideal", "error"),
    # --- contrast scaffolding ---
    (r"\bnot just\b", '"not just X, but Y" scaffolding — say the point directly', "error"),
    (r"\bnot only\b", '"not only X, but also Y" scaffolding', "error"),
    (r"\b(can't|cannot|can not) only\b", '"can\'t only X, it has to Y" scaffolding', "error"),
    (r"\bthe real \w+ is(?:n't| not)\b", '"the real X is not A, it\'s B" template framing', "error"),
    (r"\bit's not about\b", '"it\'s not about X, it\'s about Y" framing — false-equivalency family', "error"),
    # --- AI-fingerprint vocabulary ---
    (r"\bdelve\w*\b", 'Banned vocab: "delve" (48x AI fingerprint)', "error"),
    (r"\btapestr\w+\b", 'Banned vocab: "tapestry"', "error"),
    (r"\bmultifaceted\b", 'Banned vocab: "multifaceted"', "error"),
    (r"\bnuanced?\b", 'Banned vocab: "nuanced"', "error"),
    (r"\bleverag\w+\b", 'Banned vocab: "leverage" as a verb — use "use", "apply", "tap into"', "error"),
    (r"\butiliz\w+\b", 'Banned vocab: "utilize" — use "use"', "error"),
    (r"\bparamount\b", 'Banned vocab: "paramount"', "error"),
    (r"\bspearhead\w*\b", 'Banned vocab: "spearheaded" (in ~40% of AI cover letters)', "error"),
    (r"\bgroundbreaking\b", 'Banned vocab: "groundbreaking"', "error"),
    (r"\bmeaningful impact\b", 'Banned phrase: "meaningful impact" — be concrete instead', "error"),
    (r"\bproven track record\b", 'Banned phrase: "proven track record"', "error"),
    (r"\bunwavering\b", 'Banned vocab: "unwavering"', "error"),
    (r"\bthrive in( a)? fast-paced\b", 'Banned phrase: "thrive in fast-paced environments"', "error"),
    (r"\bresults-driven\b", 'Banned phrase: "results-driven"', "error"),
    (r"\bharness the power\b", 'Banned phrase: "harness the power of..."', "error"),
    (r"\bnavigat\w+ the complexit\w+\b", 'Banned phrase: "navigate the complexities of..."', "error"),
    (r"\bunlock the potential\b", 'Banned phrase: "unlock the potential..."', "error"),
    (r"\ba testament to\b", 'Banned phrase: "a testament to..."', "error"),
    (r"\bshed light on\b", 'Banned phrase: "shed light on..."', "error"),
    (r"\bfurthermore\b", 'Banned transition: "furthermore"', "error"),
    (r"\bmoreover\b", 'Banned transition: "moreover"', "error"),
    (r"\bin conclusion\b", 'Banned closer: "in conclusion"', "error"),
    (r"\bin today's\b", 'Banned opener: "in today\'s [fast-paced world / digital age]"', "error"),
    (r"\bin an era\b", 'Banned opener: "in an era where..."', "error"),
    (r"\bit is important to note\b", 'Banned filler: "it is important to note that..."', "error"),
    (r"\bit's worth noting\b", 'Banned filler: "it\'s worth noting..." (31x AI fingerprint)', "error"),
    # --- overused-AI reflective phrasing ---
    (r"\bwhat stood out\b", 'Overused: "what stood out (most)..." — say "I love that..." instead', "error"),
    (r"\bkeep coming back to\b", 'Overused: "keep coming back to..." — "I think so much about..." instead', "error"),
    (r"\btechnically current\b", 'Awkward/artificial: "technically current"', "error"),
    # --- link announcements (billboards) ---
    (r"\bi(?:'ve| have)? (?:written|wrote|blogged) about\b", 'Link billboard: "I\'ve written about..." — fold the idea in, link silently', "error"),
    (r"\bmy (?:article|post|piece|essay)\b", 'Link billboard: "my article/post..." — the idea is the point, not the authorship', "error"),
    (r"\b(?:an? )?(?:article|post|piece) (?:called|titled|named)\b", "Link billboard: naming the piece in prose", "error"),
    # --- warn-level (use sparingly / judgment) ---
    (r"\bat the intersection of\b", 'Use sparingly: "at the intersection of..." — don\'t default to it', "warn"),
    (r"\bpivotal\b", 'Use sparingly: "pivotal" (AI fingerprint; OK only in a post title)', "warn"),
    (r"\brobust\b", 'Use sparingly: "robust"', "warn"),
    (r"\bhuman-centered\b", 'Use sparingly: "human-centered" — only with concrete backing', "warn"),
    (r"\bpassionate about\b", 'Watch: "passionate about..." — usually stronger as "I care about..." / "I love..."', "warn"),
    (r"\blandscape\b", 'Watch: metaphorical "landscape" is an AI fingerprint', "warn"),
]

# Uncontracted forms that should almost always be contractions.
# Each hit is reported; >1 hit total = error (the voice spec allows at most ONE deliberate
# emphasis non-contraction per letter), 1 hit = warn (confirm it's the emphasis exception).
UNCONTRACTED = [
    (r"\bI am\b", "I'm"),
    (r"\bI have\b", "I've"),
    (r"\bI would\b", "I'd"),
    (r"\bI will\b", "I'll"),
    (r"\bit is\b", "it's"),
    (r"\bthat is\b", "that's"),
    (r"\bdo not\b", "don't"),
    (r"\bdoes not\b", "doesn't"),
    (r"\bdid not\b", "didn't"),
    (r"\bcannot\b", "can't"),
    (r"\bwould not\b", "wouldn't"),
    (r"\bthere is no\b", "there's no"),
    (r"\bI had\b(?= \w+ed\b)", "I'd"),
]


def line_of(raw, idx):
    return raw.count("\n", 0, idx) + 1


def lint(raw, cfg, prev_raw=None, is_exemplar=False):
    findings = []  # dicts: level, rule, message, line, excerpt
    prose, links = prose_of(raw)
    disabled = set(cfg["lint"]["disabled_rules"])
    link_cfg = cfg["lint"]["links"]
    words_cfg = cfg["lint"]["body_words"]
    signature = cfg.get("signature_name")

    def add(level, rule, message, line=None, excerpt=None):
        if rule in disabled:
            return
        findings.append({
            "level": level, "rule": rule, "message": message,
            "line": line, "excerpt": (excerpt or "").strip()[:120] or None,
        })

    # --- punctuation ---
    for m in re.finditer(r"—|–", raw):
        add("error", "em-dash", "Em/en dash — use a comma, period, parentheses, or colon",
            line_of(raw, m.start()), raw[max(0, m.start() - 40):m.start() + 40].replace("\n", " "))
    for m in re.finditer(r";", prose):
        add("error", "semicolon", "Semicolon — split the sentence or use a comma",
            None, prose[max(0, m.start() - 40):m.start() + 40].replace("\n", " "))

    # --- banned phrases (shipped rules + config extras) ---
    extra_rules = [(r.get("pattern"), r.get("message", "Banned phrase (from config)"),
                    r.get("level", "error")) for r in cfg["lint"]["extra_banned_phrases"]
                   if r.get("pattern")]
    for pattern, message, level in PHRASE_RULES + extra_rules:
        for m in re.finditer(pattern, prose, flags=re.IGNORECASE):
            add(level, "phrase", message, None,
                prose[max(0, m.start() - 40):m.end() + 40].replace("\n", " "))

    # --- uncontracted forms ---
    unc_hits = []
    for pattern, fix in UNCONTRACTED:
        for m in re.finditer(pattern, prose, flags=re.IGNORECASE):
            excerpt = prose[max(0, m.start() - 40):m.end() + 40].replace("\n", " ")
            unc_hits.append((m.group(0), fix, excerpt))
    if len(unc_hits) == 1:
        g, fix, excerpt = unc_hits[0]
        add("warn", "contraction",
            f'One uncontracted "{g}" (→ "{fix}"). OK ONLY if this is the deliberate emphasis '
            f"exception on the letter's strongest point — otherwise contract it.", None, excerpt)
    elif len(unc_hits) > 1:
        for g, fix, excerpt in unc_hits:
            add("error", "contraction",
                f'Uncontracted "{g}" — use "{fix}" (max one deliberate exception per letter, '
                f"and there are {len(unc_hits)} candidates here)", None, excerpt)

    # --- triads: full comma lists with EXACTLY three items ("a, b, and c") ---
    # Longer lists (4+) are fine — a real enumeration, not the AI three-beat.
    triads = []
    for m in re.finditer(r"((?:[^,.!?;:\n]+,\s+){1,6})and\s+[^,.!?\n]+", prose):
        n_commas = m.group(1).count(",")
        if n_commas == 2:
            triads.append(m.group(0).strip())
    # Warn-only: real letters legitimately carry several CONCRETE triads. The AI tell is
    # ABSTRACTION triads ("quality, trust, and better outcomes") — that's the evaluator's judgment
    # call, not a mechanical rule.
    if len(triads) >= 6:
        add("warn", "triads",
            f"{len(triads)} exactly-three-item lists. Check each: concrete enumerations are fine, "
            "abstraction three-beats ('clarity, empathy, and trust') are the AI tell.",
            None, " | ".join(t[:60] for t in triads[:4]))

    # --- links ---
    n_links = len(links)
    if not is_exemplar:
        if n_links < link_cfg["min"]:
            add("error", "links",
                f"{n_links} inline link(s) — the voice spec expects at least {link_cfg['min']} "
                "quiet link(s) from the writing-links key (proof-of-work folded into natural sentences).")
        elif n_links > link_cfg["max"]:
            add("error", "links", f"{n_links} links — more than {link_cfg['max']} reads as a link farm.")
        for text, url in links:
            wc = len(text.split())
            if wc > 9:
                add("warn", "link-anchor", f'Anchor text "{text}" is {wc} words — keep anchors 3–8 natural words.')
            if re.match(r"^(here|this|read more|link)$", text.strip(), re.IGNORECASE):
                add("error", "link-anchor", f'Anchor "{text}" — never "click here"-style anchors.')
            if text.istitle() and wc >= 4:
                add("warn", "link-anchor", f'Anchor "{text}" is Title Case — looks like a post title pasted in. '
                    "Anchors should be normal sentence words.")

    # --- exclamation energy ---
    n_excl = prose.count("!")
    if n_excl == 0:
        add("warn", "energy", "Zero exclamation points. Not required, but check: did the enthusiasm get "
            "sanded out? One where the excitement is real is the usual dose.")
    elif n_excl > 3:
        add("warn", "energy", f"{n_excl} exclamation points — 1–2 is the usual range.")

    # --- rhythm / burstiness ---
    sents = sentences_of(prose if is_exemplar else strip_headers(prose, signature))
    if len(sents) >= 8:
        lengths = [n for _, n in sents]
        mean = statistics.mean(lengths)
        cv = (statistics.pstdev(lengths) / mean) if mean else 0
        if cv < 0.35:
            add("warn", "rhythm",
                f"Low sentence-length variation (CV {cv:.2f} < 0.35). Metronomic rhythm is an AI tell — "
                "mix short punchy sentences with long ones.")

    # --- length ---
    body_words = len(re.findall(r"[A-Za-z''\-]+", strip_headers(prose, signature)))
    target = f"{words_cfg['target_min']}–{words_cfg['target_max']}"
    if body_words > words_cfg["max"]:
        add("warn", "length", f"~{body_words} words — past one dense page (target {target}). Cut, don't compress.")
    elif body_words < words_cfg["min"]:
        add("warn", "length", f"~{body_words} words — feels thin for this format (target {target}).")

    # --- preservation mode (anti-smoothing) ---
    if prev_raw is not None:
        p_prose, p_links = prose_of(prev_raw)
        if prose.count("!") < p_prose.count("!"):
            add("error", "smoothing", "Exclamation point(s) removed in revision. Restore them — "
                "energy is not a defect (see the feedback ledger's anti-smoothing rule).")
        prev_urls = {u for _, u in p_links}
        new_urls = {u for _, u in links}
        for lost in prev_urls - new_urls:
            add("error", "smoothing", f"Link removed in revision: {lost} — links may move, never silently vanish.")
        p_sents = sentences_of(strip_headers(p_prose, signature))
        if len(sents) >= 8 and len(p_sents) >= 8:
            def cv_of(ss):
                ls = [n for _, n in ss]
                m = statistics.mean(ls)
                return (statistics.pstdev(ls) / m) if m else 0
            if cv_of(p_sents) > 0 and cv_of(sents) < cv_of(p_sents) * 0.8:
                add("warn", "smoothing", "Sentence rhythm got noticeably more uniform in revision "
                    f"(CV {cv_of(p_sents):.2f} → {cv_of(sents):.2f}). Check for over-smoothing.")
        p_words = len(re.findall(r"[A-Za-z''\-]+", strip_headers(p_prose, signature)))
        if body_words < p_words * 0.85:
            add("warn", "smoothing", f"Word count dropped {p_words} → {body_words} in revision — "
                "confirm nothing personal/alive was cut beyond the cited fixes.")

    return findings, {"words": body_words, "links": n_links, "exclamations": n_excl}


def strip_headers(prose, signature_name=None):
    """Drop Re:/date/salutation/signature lines so word counts reflect the body."""
    sig = re.escape(signature_name.strip()) + "$" if signature_name else None
    lines = []
    for ln in prose.splitlines():
        s = ln.strip()
        if re.match(r"^(re:|dear |sincerely|warmly|best,|looking forward)", s, re.IGNORECASE):
            continue
        if sig and re.match(sig, s, re.IGNORECASE):
            continue
        if re.match(r"^\w+day, \w+ \d{1,2}, \d{4}$", s) or re.match(r"^\w{3}, \w+ \d{1,2}, \d{4}$", s):
            continue
        lines.append(ln)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Deterministic cover-letter lint")
    ap.add_argument("file", help="letter file (.md or .txt)")
    ap.add_argument("--prev", help="previous draft — enables anti-smoothing preservation checks")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--exemplar", action="store_true", help="lint an exemplar body (skips link-count rules)")
    ap.add_argument("--config", default=str(Path(__file__).resolve().parents[3] / "PRIVATE__YOUR_FILES_GITIGNORED" / "04-TAILOR__YOUR_PRIVATE_INFO" / "cover-letter" / "config.json"),
                    help="config JSON (default: config.json beside this script; falls back to defaults)")
    args = ap.parse_args()

    cfg = load_config(args.config)

    try:
        raw = load_text(args.file)
    except OSError as e:
        print(f"cannot read {args.file}: {e}", file=sys.stderr)
        return 2
    prev_raw = None
    if args.prev:
        try:
            prev_raw = load_text(args.prev)
        except OSError as e:
            print(f"cannot read --prev {args.prev}: {e}", file=sys.stderr)
            return 2

    # For exemplar files, lint only the letter body below the "---" separator.
    if args.exemplar and "\n---\n" in raw:
        raw = raw.split("\n---\n", 1)[1]

    findings, stats = lint(raw, cfg, prev_raw, is_exemplar=args.exemplar)
    errors = [f for f in findings if f["level"] == "error"]
    warns = [f for f in findings if f["level"] == "warn"]

    if args.json:
        print(json.dumps({"file": args.file, "stats": stats, "errors": errors, "warnings": warns}, indent=2))
    else:
        print(f"lint: {args.file}")
        print(f"  ~{stats['words']} body words · {stats['links']} links · {stats['exclamations']} exclamation(s)")
        for f in errors:
            loc = f" (line {f['line']})" if f.get("line") else ""
            print(f"  ERROR{loc}: {f['message']}")
            if f.get("excerpt"):
                print(f"         …{f['excerpt']}…")
        for f in warns:
            print(f"  warn : {f['message']}")
            if f.get("excerpt"):
                print(f"         …{f['excerpt']}…")
        print(f"  => {len(errors)} error(s), {len(warns)} warning(s)")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
