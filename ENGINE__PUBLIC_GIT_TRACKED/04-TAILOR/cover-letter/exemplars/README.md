# Exemplars — your annotated real letters

The writer and evaluator learn your register by example, not just rules. This folder holds real
cover letters **you** wrote (or approved), each annotated so the agents know *why* it's here.
The files themselves are gitignored — only this README is tracked.

## What to include

- **Exactly one GOLD standard** — your best letter, the one the evaluator compares every draft
  against. Name it so the status is visible: `company-YYYY-MM-GOLD.md`.
- **Optionally one NEGATIVE example** — a letter you weren't happy with, annotated with what's
  wrong. The most instructive negative is a *recent, rule-adjacent* one: a letter that sounds
  competent and is still wrong teaches far more than an obviously bad one.
  Name it `company-YYYY-MM-NEGATIVE.md`.
- **2–4 more good letters** for range (different openers, different structures, different eras).
  Name them `company-YYYY-MM.md`.

Keep the set small and current. Five letters that genuinely represent you beat fifteen that don't.
`/cover-letter-intake` builds this set with you from your past letters.

## File format

An annotation header, then `---`, then the letter body verbatim:

```markdown
# Exemplar: Company — Role (M/D/YY)

**Status: GOLD STANDARD.** (or NEGATIVE EXAMPLE, or a one-line "why this letter is here")

**Why it's here:** 4–8 bullets naming the specific moves that make it good (or bad): the opener
shape, the personal thread, how links are folded in, how a gap was handled, what to copy — or,
for a negative, each failure mapped to the voice-spec rule it breaks.

**Links used (anchor text → target):** list them, if any.

---

Re: Role Title (Day, Month D, YYYY)

Dear Company team,

[the letter, verbatim, exactly as sent]
```

Everything above the `---` is annotation; everything below is the letter. The lint understands
this split: `lint_cover_letter.py <file> --exemplar` lints only the body (and skips link-count
rules, since older letters may predate your link strategy).

## Ground rules

- **Verbatim bodies.** Never "improve" an exemplar — the whole point is what you actually sent.
- **Annotate honestly.** If the GOLD letter has one flaw, note it ("survives here because X;
  don't copy it by default") so the agents don't learn the flaw as a feature.
- **Update deliberately.** When a new letter beats your GOLD, promote it and demote the old one —
  don't accumulate several "golds."
