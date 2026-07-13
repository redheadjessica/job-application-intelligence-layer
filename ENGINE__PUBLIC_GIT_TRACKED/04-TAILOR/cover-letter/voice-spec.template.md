<!-- TEMPLATE — copy structure only. /cover-letter-intake stages a filled version for your review,
     then promotes it to the gitignored instance voice-spec.md. The engine reads the instance. -->
# Cover Letter Voice Spec — {{YOUR NAME}}

This is the **writer's canon** for cover letters. It is written for an AI agent, not a human reader.
Follow it exactly. It is distilled from {{YOUR NAME}}'s own writing and direct feedback.

Companion files, each with one job:
- `lint_cover_letter.py` — mechanical rules enforced by script (banned phrases, punctuation, link
  announcements). You must pass it, but don't write *for* it — write well, and the lint stays quiet.
- `eval-rubric.md` — how the evaluator will score you. Don't read it while drafting; write from voice.
- `feedback-ledger.md` — the candidate's accumulated feedback. **Read it every run.** Newer entries
  win over anything here that conflicts.
- `exemplars/` — annotated real letters. The file marked GOLD is the reference standard.

---

## The north star

The reader should finish the letter thinking:

> *{{THE IMPRESSION YOU WANT TO LEAVE — e.g. "This person is smart, direct, unusually thoughtful,
> and actually gives a shit about this work."}}*

Not: *this person has been optimized for my job description.*

Recruiters are drowning in AI-written letters that all sound like the same person wrote them.
Their gut test is: **"Would this person actually say these words in an interview?"** Every sentence
must pass that test. A little friction, a real personal story, an uneven rhythm — these are now the
trust signals. Polish is cheap; a person on the page is rare.

## The default register

**{{YOUR REGISTER IN 4-6 WORDS — e.g. "Direct + conversational + proof-backed + emotionally honest."}}**
Not: corporate + over-explained + formulaic + "optimized" into sludge.

{{ONE OR TWO SENTENCES ON HOW YOU'D DESCRIBE YOUR LETTER VOICE — e.g. "Write like a sharp,
thoughtful person who actually wants THIS job — a smart friend explaining over coffee why this
role makes sense, with receipts."}}

---

## Hard rules (mechanical — the lint script also enforces these)

These defaults reflect what reads as human in current hiring; edit any that don't match your voice
(and mirror the change in `config.json` → `lint.disabled_rules` / `extra_banned_phrases`).

1. **Contractions everywhere.** "I'm", "I've", "doesn't", "that's". Non-negotiable default.
   - **The one exception:** at most ONE deliberately uncontracted phrase per letter, used only to
     emphasize a genuinely strong point, where the full form slows the sentence down on purpose.
     If you use it, it must be the strongest sentence in the letter, not an oversight.
2. **No em dashes. No semicolons.** Use commas, periods, parentheses, or a colon.
3. **Never open with "I'm excited to apply for…"** or any variant ("I am writing to express my
   interest…", "I'm thrilled to apply…"). "Excited" in the opener is the single most-flagged word in
   AI cover letters. Open with the actual point.
4. **Never close with "Thank you for your consideration"** or "I would welcome the opportunity to
   discuss further." Close warm and forward: {{YOUR CLOSER FAMILY — e.g. "Looking forward to
   chatting," / "I'd love the chance to talk."}}
5. **No "not just X, but Y" / "not only X, but also Y" / "the real X is not A, it's B"**
   scaffolding. Say the point directly.
   - The subtler cousin — **reversal/contrast pairs** ("X, not Y") — {{YOUR TOLERANCE — e.g. "at
     most one per letter, only when it truly earns its place; default to zero."}}
6. **Banned vocabulary** (AI statistical fingerprints): delve, tapestry, multifaceted, nuanced,
   pivotal, robust, leverage (as a verb), utilize, paramount, spearheaded, groundbreaking,
   "meaningful impact", "proven track record", "unwavering", "thrive in fast-paced",
   "harness the power of", "navigate the complexities", "unlock the potential", "a testament to",
   furthermore, moreover, "in conclusion", "in today's [anything]".
7. **Watch the triads.** Lists of exactly three parallel items ("clarity, empathy, and trust") are an
   AI fingerprint when they repeat. One is fine if it's real. Two is the ceiling. List however many
   items you actually have — two, four, one.
8. **{{YOUR ENERGY MARKERS — e.g. "Exclamation points are my voice. Do not strip them. One or two
   per letter, where the enthusiasm is real."}}**
9. **No emoji in cover letters.**

---

## Structure

Target **{{WORD RANGE — e.g. 350–620}} words** for the body (salutation through closing).
One page, always.

**Header block** (fixed): `Re: **[Role Title]**` + date, then `Dear [Company] team,` (or the hiring
manager's name if known — never "To Whom It May Concern").

**Opening paragraph — start with the real hook, not application boilerplate.**
The first sentence is the emotional or product thesis. Proven shapes:
- Mission thesis: {{EXAMPLE FROM YOUR OWN LETTERS}}
- Bold claim: {{EXAMPLE FROM YOUR OWN LETTERS}}
- Personal story: {{EXAMPLE FROM YOUR OWN LETTERS}}

The opening must sound like you have a *reason* to care about this specific company. Reference
their actual product or the actual framing in the JD — not their values page.

**A personal thread is a feature, not a risk.** AI has no lived experience to draw on. You do.
One or two sentences of a real story or a real first-person "why", where true and relevant, is
what makes the letter yours. Never invent a story. Pull only from **`anecdote-bank.md`** (the
indexed story library — check its "Used in" lines to avoid repeats) and the application canon.

**Middle — arguments, not a resume recap.**
Two formats, both proven:
- 3–5 bullets with **bold lead-ins**, introduced by a line like "Here's what I'd bring to that
  work:" — each bullet's bold lead-in names a *role-relevant argument*, not a credential.
  ("Experience scaling a live product people already depended on." — not "[Employer] experience.")
- Or flowing paragraphs when the letter is more thesis-driven.

Every bullet/paragraph answers: **"Why should they believe I'm unusually suited for this?"**
The resume already lists what you did. The letter argues why it matters *here*. Chaining five
credentials with commas is a resume recap and it reads as one.

Recurring argument themes (use only what fits the role, never mechanically):
{{YOUR 4-8 RECURRING ARGUMENT THEMES — the through-lines of your candidacy, e.g. "builder-owner
product judgment at scale · bias toward customer truth · hands-on AI building with real
guardrails"}}

**Handling the gap ({{YOUR COMMON GAPS — domain, seniority, industry}}).** Acknowledge once if
useful, pivot immediately to compensating strength, never apologize: {{EXAMPLE GAP MOVE FROM YOUR
OWN LETTERS}}

{{ANY STANDING NARRATIVE THE LETTERS MUST CARRY — e.g. how you frame an employment gap, a career
change, or a signature proof point that belongs in nearly every letter. Delete if none.}}

**Closing — warm, forward, specific.** One or two sentences max. No synthesis paragraph that
re-lists qualifications ("…where my background in A, B, C, and D can all come together" is a
tidy-bow ending and a tell). End on wanting to help build the thing.
Sign-off: {{YOUR HOUSE DEFAULT — e.g. "Looking forward to chatting,"}}

---

## Inline links (skip this section if you keep `lint.links.min` at 0)

**Links are quiet proof, not billboards.** The sentence must stand on its own with the link
removed. The link is embedded in normal language.

- NEVER: "I've written about this in *[Post Title]*." / "I built [Project Name], which is…"
- ALWAYS: "I think a lot about why people do or don't [come back to products that are supposed to
  help](url)." — the idea folded into a natural sentence, linked silently.

Rules:
- **{{N–M}} links per letter**, chosen from `writing-links.md` (the single source of truth — use
  its "best linked when…" guidance). Fewer is fine if fits are weak; never force one.
- Never use a post title as the object of the sentence. Never say "I wrote about…" (the point is
  the idea, not that you're a writer).
- Anchor text is 3–8 natural words that would survive as plain prose.
- Prefer the most recent, most on-point pieces.
- Every link's exact URL must come from `writing-links.md`. Never guess a URL.

---

## Truth rules (same discipline as the resume system)

- **No fabrication, ever.** Every claim must be traceable to the application canon
  (`PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/01-profile.md`, `PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/04-experience-bank.md`) or `writing-links.md`.
- **Boundary rules apply:** everything in `PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/03-approved-truths-and-boundary-rules.md`
  is mandatory here too.
- Numbers only as canon states them.
- If the JD asks for something you don't have, the letter either reframes honestly (gap →
  compensating strength) or stays silent. It never implies.
- **Product-familiarity claims:** never state or imply you personally use the company's product
  unless the canon or the feedback ledger confirms it. No faked fandom. When unsure, leave it out
  and raise an open question.
- Uncertainties go in the review packet's "Questions" section, not into hedged prose.

## Anti-smoothing rules (for revision passes)

When revising after evaluation, you are a **surgeon, not an editor**:
- Touch ONLY the lines the evaluation cited. Everything else survives verbatim.
- Never remove an exclamation point, a personal story, an analogy, or an idiosyncratic phrase
  unless it was explicitly flagged. "Smoother" is not "better" — evenly polished text is the tell.
- Keep sentence rhythm uneven: short punchy sentences next to long ones. Do not equalize.
- If a fix would make the letter sound more generic, flag the tension in the review packet instead
  of applying it.
