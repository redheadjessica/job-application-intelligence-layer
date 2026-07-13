---
name: cover-letter-intake
description: Onboarding + update for the cover-letter system. Reads a person's past cover letters and published writing, distills their voice into a proposed voice spec, exemplar set, anecdote bank, and writing-links key, asks a few sharp questions, then STAGES everything in a review folder for approval before promoting to the private instances in 04-TAILOR/cover-letter/. Run after /intake (it builds on the application canon); re-run anytime to add letters or refresh the canon.
---

# Cover Letter Intake

You are setting up (or updating) the cover-letter system for a person. When you're done, the
`cover-letter` workflow writes letters in *their* voice — grounded in their real letters, their
real stories, and their real published work — instead of generic AI letters.

## North star

**The letter should sound like them on their best day — never like you.** Your default writing
voice is exactly what this system exists to avoid. Everything you distill must come from *their*
words: their past letters, their writing, their answers. Where you have no evidence, ask or leave
a placeholder — never fill a voice gap with your own taste.

And the standing rule: **never invent.** Stories, claims, and URLs come only from what they give
you. A voice spec built on invented examples poisons every letter after it.

## Prerequisite

This skill builds on the application canon (`04-TAILOR/01-profile.md`,
`04-TAILOR/04-experience-bank.md`, `04-TAILOR/03-approved-truths-and-boundary-rules.md`). If those
don't exist yet, run `/intake` first — the letter writer needs them for truth-checking claims.

## First run vs. update (one command, two modes)

- **Look for an approved setup:** does `04-TAILOR/cover-letter/voice-spec.md` exist with a
  `<!-- jail-approved: ... -->` marker?
- **No → FIRST RUN.** Say: *"Looks like this is your first cover-letter intake. I'll study your
  past letters and writing, then propose a voice spec for you to check."* Run the full flow.
- **Yes → UPDATE.** Say: *"You already have an approved cover-letter setup. I'll check what's new
  — new letters, new published pieces, new feedback — and help you update."* Stage **only the
  delta** (a new exemplar, a new writing-links row, a ledger entry), not a full regeneration.

## Architecture: templates → staged review → generated instances

Same mechanism as `/intake`:

1. **Tracked templates** in `04-TAILOR/cover-letter/*.template.md` + `config.template.json` are
   the skeletons. Read them for structure. **Never fill a template in place.**
2. **Staged review** lives in `__READY TO REVIEW/<MM-DD-YY> - Cover Letter Intake/` (folder via
   `date +%m-%d-%y`). Instantiate the review files from the skeletons in
   `.claude/skills/cover-letter-intake/review-templates/` and fill them with real proposed content.
3. **Generated instances** (bare names in `04-TAILOR/cover-letter/`, gitignored) are written
   **only after approval**, by faithfully transcribing the reviewed content, each markdown
   instance stamped `<!-- jail-approved: YYYY-MM-DD -->` on its first line.

## What you need from them (offer every path: paste in chat, point at a folder, drop files)

1. **Past cover letters — the most important input.** Ideally the versions they actually *sent*
   (PDFs fine; use the pdf skill). 3–8 letters is plenty. Ask which they were proudest of and
   whether any felt off or embarrassing in hindsight — that's your GOLD / NEGATIVE seed.
2. **Any feedback they've received or given on letters** — a coach's notes, their own edits to an
   AI draft, "I always delete sentences like X." Seeds the feedback ledger.
3. **Published/public work to link** (posts, portfolio, projects, talks) — URLs preferred; fetch
   with `ENGINE__PUBLIC_GIT_TRACKED/02-PREP/prep_job_urls.py` when useful. Optional: if they have none, the system runs
   linkless (`lint.links.min: 0`).
4. **Their letter/resume template** (or a PDF of a real sent letter) — to measure font, size, and
   text color for `config.json` → `docx` and the formatting spec. If they have no template, keep
   the shipped defaults and say so.
5. **If no past letters exist:** fall back to their general writing (emails they like, posts) plus
   a short interview, and mark the voice spec as low-evidence — the first few real letters they
   approve become the exemplars.

## Making sense of it — how to distill a voice spec

Study the letters like an editor, not a fan. For each, note:
- **Register:** contractions? exclamation points? emoji? formality? sentence-length spread?
- **Openers and closers** they actually use (collect verbatim examples — these fill the voice
  spec's "proven shapes" and "closer family" slots).
- **Structure:** bullets vs paragraphs; how arguments are made; how gaps are handled.
- **Personal threads:** every true story or first-person "why" → a proposed anecdote-bank entry
  (in *their* words, with source noted).
- **Recurring argument themes** — the 4–8 through-lines of their candidacy that show up across
  letters.
- **Tells to ban:** anything they self-edited away, anything they called out as "not me" →
  proposed `config.json` `extra_banned_phrases` and voice-spec hard-rule edits.
- **Candidate GOLD:** the letter that best represents them (their pride pick wins over yours).
  **Candidate NEGATIVE:** one they disliked, annotated by what's wrong. Draft the annotation
  headers per `04-TAILOR/cover-letter/exemplars/README.md`.

The shipped template defaults (contractions, no em dashes, banned AI vocabulary, quiet links) are
strong priors — keep them unless their letters *consistently* contradict one (e.g. a genuinely
formal voice with no contractions). When their evidence contradicts a default, follow the evidence
and note the change (mirror it in `config.json` → `lint.disabled_rules`).

### Sharp questions (batched — ask once, not a drip)

Only what the letters can't tell you: signature name exactly as they sign · pride pick + regret
pick confirmation · closer preference · how much energy/enthusiasm feels like them · any hard
"never" words or moves · link strategy (do they want links? how many feels right?) · anything in
a story you may NOT say (guardrails).

## Staging — the review folder

Fill, in order (from `review-templates/`):

```
START HERE.md
1 - Voice Spec Review.md
2 - Exemplars Review.md
3 - Anecdote Bank Review.md
4 - Writing Links Review.md        (skip + note if they have no public work)
5 - Config + Formatting Review.md
6 - Open Questions.md
```

Each file carries the **real proposed content** (what they review is what gets promoted) plus a
short "what to check" note. Quote their own letters when showing voice rules — evidence, not
assertion. **No canonical instance is written in this step.** Never hard-wrap prose in these files
— one paragraph = one line.

## Review loop → promotion

Same discipline as `/intake`:
- Guide them in chat: start with `START HERE.md`; feedback by voice/chat or direct edits (reread
  edited files from disk before promoting). **Silence is never approval.**
- The explicit gate: *"Does this sound like you on your best day — good enough to write your next
  letter from?"*
- On approval, write the instances in `04-TAILOR/cover-letter/`:

| Review file | Promotes to |
|---|---|
| `1 - Voice Spec Review.md` | `voice-spec.md`, `eval-rubric.md` (rubric = template with their GOLD/NEGATIVE names + any voice-check edits) |
| `2 - Exemplars Review.md` | `exemplars/<company>-<YYYY-MM>[-GOLD\|-NEGATIVE].md` (annotation header + `---` + verbatim body) |
| `3 - Anecdote Bank Review.md` | `anecdote-bank.md` |
| `4 - Writing Links Review.md` | `writing-links.md` (omit if none) |
| `5 - Config + Formatting Review.md` | `config.json`, `formatting-spec.md` |
| (always, near-empty is fine) | `feedback-ledger.md` (seeded with any confirmed feedback from step 2 of inputs), `feedback-queue.md` (header only) |

- **Promote faithfully** — transcribe, don't improve. Exemplar bodies stay verbatim.
- After promoting, **verify mechanically:** run
  `.venv/bin/python3 04-TAILOR/cover-letter/lint_cover_letter.py "04-TAILOR/cover-letter/exemplars/<gold>.md" --exemplar`
  — it should exit 0 (warnings fine). If the GOLD errors, the annotation should acknowledge why
  (their voice overrides the default rule → disable it in config) — resolve before finishing.

## Wrap

Summarize: what was promoted, the GOLD pick, how many anecdotes/links were banked, any low-evidence
areas to revisit, and the next move: *"Run `cover-letter {job: "<path>"}` on a job you're tailoring
— then judge the draft hard; your corrections become the feedback ledger."* Remind them the
instances hold personal data and are gitignored, so they're never committed.
