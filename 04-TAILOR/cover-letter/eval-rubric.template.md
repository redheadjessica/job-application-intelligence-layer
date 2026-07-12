<!-- TEMPLATE — copy structure only. /cover-letter-intake stages a filled version for your review,
     then promotes it to the gitignored instance eval-rubric.md. The engine reads the instance.
     Most of this file is mechanism and works as-is; the {{PLACEHOLDERS}} tie it to YOUR exemplars. -->
# Cover Letter Evaluation Rubric

This is the **evaluator's canon**. It defines two separate scored evaluations — **Fit** and
**Voice** — plus the mandatory self-pushback step. The evaluator never rewrites the letter; it
cites lines and hands findings back.

**Bias warning (read first):** you are an LLM judging LLM output. Your default preference is text
that sounds like what *you* would write — smooth, balanced, evenly polished. That is exactly what
this system exists to prevent. When in doubt between "polished" and "sounds like a real person who
wants this job," the real person wins. **Over-smoothing is a defect, not an improvement.** A
revision that got safer and blander than its predecessor scores LOWER, even if it "fixed" things.

Ground your judgments in comparison, not abstraction: the question is never "is this good writing?"
— it is **"does this sound more like the GOLD exemplar or more like generic AI output?"**

---

## Inputs to read, in order

1. `voice-spec.md` — the rules the writer was following
2. `feedback-ledger.md` — the candidate's accumulated feedback (newest entries win)
3. `exemplars/` — all of them, including any NEGATIVE example
4. The job `.txt` and, if present in the job folder, the `application_resume_output - … .md`
   (it contains the role analysis and evidence selection)
5. The draft letter

## Eval 1 — Fit (score 1–5)

Does this letter argue for **this** job's actual needs?

| Score | Anchor |
|---|---|
| 5 | Every argument maps to a real, primary need in the JD; the letter shows the candidate understood what the role is actually for {{OPTIONAL: EXAMPLE FROM YOUR GOLD EXEMPLAR}}. The links chosen are the ones writing-links.md recommends for this kind of role. |
| 4 | Arguments fit the role well; one bullet or link is generic or second-best for this lane. |
| 3 | Competent but interchangeable — most of this letter could be sent to a different company in the same category without edits. Mission connection asserted rather than shown. |
| 2 | Arguments answer needs the JD doesn't have, miss its stated priorities, or recap the resume instead of arguing. |
| 1 | Wrong emphasis throughout; reads as a template with the company name swapped in. |

Fit checks:
- **The JD's top 2–3 stated priorities each get answered** (or one is consciously conceded via the
  gap-handling move). Identify the priorities yourself from the JD; don't trust the letter's framing.
- **Company specificity:** references their actual product/framing, not their values page. The
  "About Page Callback" (opening with a line scraped from their mission statement) is a flag.
- **Perfect JD keyword mirroring is a defect** — real candidates don't echo that cleanly.
- **Link selection:** are these the links writing-links.md's "best linked when…" guidance would
  pick for this role? Flag stronger swaps.
- **Truthfulness spot-check:** claims traceable to the application canon; every rule in
  `04-TAILOR/03-approved-truths-and-boundary-rules.md` respected; no invented stories.

## Eval 2 — Voice (score 1–5)

Does this sound like the candidate — a real human the recruiter would recognize in an interview?

| Score | Anchor |
|---|---|
| 5 | Indistinguishable in register from the GOLD exemplar: real hook, personal thread, arguments not credentials, quiet links, uneven rhythm, warm close. At least one line only this candidate would write. |
| 4 | Sounds like them; one passage drifts flat or one link is louder than it should be. |
| 3 | Rule-compliant but voiceless — no personal thread, even-cruise rhythm, uniform confidence. Technically clean AI text. |
| 2 | Multiple tells: announced links, resume-recap paragraph, triad pileup, boilerplate open/close, moral-bow ending. {{IF YOU HAVE A NEGATIVE EXEMPLAR: "(This is the [name] letter. It scores 2.)"}} |
| 1 | Corporate sludge; would be flagged as AI on a skim. |

Voice checks (cite the line for every finding):
- **The interview test:** would the candidate actually say this sentence out loud? Flag any
  sentence that wouldn't survive being spoken.
- **Opening:** is the first sentence the actual point, or throat-clearing?
- **Person on the page:** is there a true personal thread (story, first-person "why")? Its absence
  caps Voice at 3.
- **Arguments vs recap:** does any paragraph chain 3+ credentials with commas? That's a recap.
- **Links:** quiet proof or billboards? Would each sentence stand with the link removed?
- **Rhythm:** short sentences next to long ones, or a metronome? Paragraphs varied or uniform?
- **Energy:** enthusiasm present where real? (Stripped energy = smoothing.)
- **Ending:** forward and warm, or a tidy synthesis bow that re-lists qualifications?
- **Emphasis exception:** at most one deliberate non-contraction, and only on a genuinely strong
  point. More than one, or one on a weak sentence, is a miss.

## Comparison pass (mandatory)

Read the draft immediately after re-reading the GOLD exemplar. Answer in one sentence each:
1. Which letter has the stronger first line, and why?
2. Name one thing the GOLD exemplar does that this draft doesn't.
3. Name one thing this draft does *better* than the GOLD exemplar (if genuinely nothing, say so —
   a draft that beats the gold standard somewhere is the goal, not sacrilege).

## Self-pushback (mandatory, before finalizing scores)

Argue against your own scores in 2–4 sentences each direction:
- **Why might Fit be lower than I scored?** (Did I grade the letter's own framing instead of the JD's?)
- **Why might Voice be higher than I scored?** (Am I penalizing friction/quirk that is actually the
  point? Am I rewarding smoothness?)
- Adjust if the pushback wins. Record both the original and final score if they differ.

## Output

Write the full evaluation to the path the orchestrator gives you, then return the structured
summary it asks for. Findings rules:
- Max 8 findings, each tagged **must-fix** (violates voice-spec / untrue / misses a top JD priority)
  or **consider** (would improve, writer's call).
- Every finding cites the exact line text it's about and says *why* per this rubric — never just
  "this could be stronger."
- Never propose replacement copy longer than a phrase; the writer owns the words.
- If the letter is strong, say so and stop. Do not manufacture findings to look thorough. An empty
  must-fix list is a valid, good outcome.

## Re-evaluation (after a revision)

Same rubrics, plus:
- **Preservation check:** did anything good disappear? Compare against the prior draft — lost
  exclamation points, lost stories, equalized rhythm, genericized phrasing. Any of these is a
  must-fix on the *revision*, scored as smoothing.
- Verify each prior must-fix was actually addressed (not just reworded around).
- Remaining concerns after this pass go to the review packet as flags for the candidate, not
  another loop.
