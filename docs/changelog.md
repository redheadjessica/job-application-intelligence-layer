# JAIL Changelog

Project changelog. Reverse chronological. Maintained as readable project memory: what
changed, what was explored, and why it mattered — not a commit log. Git history already
holds the granular record; this file is the curated account.

Add rough entries here during normal work (see `scripts/README.md` for the format).
Run `python3 scripts/doc_synthesis.py` to consolidate them into readable threads.


<!-- changelog-processed-through: bd576955caf6495566fc88fcf9b7b5aadb8d10c8 -->
---

## 2026-07-16 — Reconcile gap found: a failed agent's findings can be silently lost (worked around by hand; not yet fixed)

During the 07-16 reconcile batch, the Paperless Post agent wrote its reconcile report to the folder but
then failed its structured-output return (retry cap), so the Synthesize stage never received its
findings — no ledger entry, no queue items, no anecdote harvest. A follow-up run then skipped the folder
as "already reconciled" because discovery treats report-presence as done. Findings were merged by hand
this time (ledger entry, anecdote `habitual-gathering-host`, annotations). Real fix for later: discovery
should verify the folder is represented in the ledger (not just that a report file exists), or the
per-folder agent should only write its report after a successful return.

## 2026-07-16 — Tailor-output usability overhaul from Bloomerang reconcile feedback (engine half)

User feedback after completing the Bloomerang application, split explicitly (at her request, with sign-off)
into user-specific lessons (routed through /reconcile into her learning ledger/queue) and engine changes
for every user. The engine half, all in `04-TAILOR/00-job_application_agent.md` unless noted:

- **"Questions for the candidate" discipline:** the section is for genuine work-history/experience gaps
  whose answers change the resume. Comp FYIs move to Final Risks/Notes; "reminder: this optional section
  is optional" boilerplate is banned outright (the recurring Content Opportunity disclaimer was appearing
  in output after output). Flagging a genuinely NEW bullet for confirmation stays — that's the section's
  actual job.
- **Delta-only output against the chosen base:** unchanged role sections are now ONE line ("No changes —
  use [base]'s section as-is"), never restated bullets; the file reads as a change list, not a resume
  transcript. Trigger: outputs had ballooned to where finding the real edits took longer than making
  them (e.g. "replace X with Y" where Y was word-for-word identical to the base's X).
- **Summary rule (generic version, per her approval):** don't spend summary space duplicating what's
  visible in the first experience bullet — summary sells role fit. (Her stricter Ascend-specific version
  goes in her private files via reconcile.)
- **Content Opportunity is now an intake opt-in** (intake SKILL.md Step 5 + spec Step 9.5): intake asks;
  decliners never see the section; opt-ins get a content library built from their Voice-family writing so
  suggestions build on what they've covered. Was a her-specific feature that leaked into the generic
  engine. Her profile already records always-on, so the gate changes nothing for her.

---

## 2026-07-16 — "Base Resume Used" is finally populated; new "Cover Letter?" column

- **The bug, and how long it had been there:** `vet-jobs.js` wrote `Base Resume Used` as an empty
  string with the comment *"filled later by the tailor step"* — but `tailor-jobs.js` never touched
  the rankings files at all. The tailor agent has ALWAYS returned `recommended_base` in its
  `CONFIRM_SCHEMA`; the value was simply discarded on return. So the column was blank in every
  batch ever produced, and the data (which existed all along, inside each per-job
  `application_resume_output*.md`) had to be reconstructed by hand. Jessica had asked about this
  column repeatedly; it read as the system ignoring her, when really it was a handoff that was
  specified in a comment and never built.
- **Fix:** new shared `ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/update_rankings_row.py`. Both
  `tailor-jobs.js` (new `Record` phase → writes `--base`) and `cover-letter.js` (new `Record`
  phase → writes `--cover-letter`) now call it per job. It edits the batch's rankings CSV **and**
  XLSX **in place** — never regenerating — so manual edits, formatting, and local column renames
  survive.
- **Matching is by canonical URL first, job filename second.** Filename alone is not reliable: the
  same posting gets re-fetched under different slugs across batches (Everyday Health exists as
  `...__pm.txt` AND `...__everyday-health.txt`; Google as `google__...` AND
  `product-manager-google-docs__...`), all resolving to one URL via `prep_common.normalize_url`.
  Verified: the writeback lands correctly even when the passed filename is outright wrong.
- **`terse_base()` normalizes the agent's verbose return** into the tracker's house style —
  `'Anthropic — PM, Consumer (6/25/26), copied and renamed to …pages'` → `'Anthropic — PM, Consumer
  (6/25/26)'`; `'(Jan 2026)'` → `'(1/26)'`; `Professional Services` → `Prof. Services`. Matches the
  format Jessica had been hand-entering.
- **New `Cover Letter?` column** (appended last, after `Comp Fit`) answers "which of these already
  have a letter written?" at a glance. New batches get it from `vet-jobs.js`; older 24-column
  batches have it appended automatically on first writeback.
- **A miss is loud, never silent:** if no rankings row matches, the script prints a `WARNING:` line
  naming the key it tried, and the calling agents are explicitly instructed to report it verbatim
  and NOT retry or "fix" it. A silent miss is precisely how the column stayed empty unnoticed for
  so long.
- **Column-count regression check:** `HEADERS` (25) and `dataCells()` (25) verified equal by
  evaluating the real code, not by eyeballing.
- Column renames are tolerated by prefix-matching headers (Jessica's reads
  `"Base Resume Used - Jess-Requested Custom Field"`).

---

## 2026-07-16 — Mission/Scope Fit notes: back to one human sentence, math moved to an optional detail field

- **The problem:** `mission_fit_notes` and `scope_fit_notes` had drifted into dense sub-factor math
  ("Desire = 66 (Mission 11/30 + Role 25/30 + Brand 18/20 + Culture 10/15 + Stage 2/5)...") instead
  of a plain sentence a human can read at a glance. Nothing in the scoring card asked for this —
  it was emergent agent behavior from a "compute it, don't eyeball it" rubric, and the schema's old
  description ("one tight phrase each") was too weak to hold the line against it.
- **Fix (shared engine, `vet-jobs.js` — applies to every ranking run, not just this user's):**
  `mission_fit_notes`/`scope_fit_notes` are now explicitly required to be ONE plain-English
  sentence with no "=", "/", or "+" notation, with a concrete good/bad example pair in the schema
  description itself. Two new OPTIONAL fields, `mission_fit_detail`/`scope_fit_detail`, carry the
  full sub-factor math / hiring-thesis reasoning for anyone auditing a score later — but only the
  Markdown report shows them (indented under the summary line); the CSV/XLSX tracker (what people
  actually scan day to day) never touches the detail fields at all.
- **Not regenerated:** existing rankings (07-16-26, and the archived 07-14-26 project) were left
  as-is — this is a standing-instruction fix for future runs, not a backfill.
- **Also archived** the 07-14-26 historical-rescore project (`build_rescore_workbook.py` + its
  batch folder) to `PRIVATE__YOUR_FILES_GITIGNORED/_ARCHIVED_ONE-OFF_PROJECTS/` — it was a one-off
  built to compare an old vs. new scoring rubric, no longer needed now that there's a single
  resume/scoring source of truth again. This also removes the recurring risk where a formatting
  fix applied to that one-off script's duplicated styling logic didn't propagate to the shared
  `make_rankings_xlsx.py` engine (see the lane-color/alignment fix earlier today) — one less place
  for the same bug to silently reappear in.

## 2026-07-16 — System-level fix: a job can no longer be scored on unverified fetch content

- **The incident:** Microsoft's "Senior Product Manager - AI Skilling" posting failed to fetch
  cleanly — the captured file was ~488KB of the careers site's JS theme config and nav chrome,
  zero actual job text. It was still scored (all four dimensions, final score 44) and shown in
  the rankings as if it were a real read. The user caught it by hand, asking "does Microsoft
  being fully remote change any scores?" — it shouldn't have taken a manual catch.
- **Root cause, found and fixed:** `prep_common.classify()` only ran its "does this look like a
  real job posting" content-marker check when the fetched body was under ~1400 characters. A
  long body full of junk sailed through as `usable` on length alone. Fixed: the content-marker
  check now applies unconditionally, regardless of body length.
- **Hard rule added (Jessica, 7/16/26), three layers deep:**
  1. **Prep now auto-retries with a second fetch method** before quarantining anything.
     `prep_common.process_urls()` takes an optional `fetch_fallback`; `prep_job_urls.py` (the
     primary requests-based fetcher) now automatically spins up Playwright as that fallback
     when installed, and clearly notes in the manifest/report when no fallback was available
     to try (rather than silently only attempting once).
  2. **The scoring agent itself must verify content before scoring** (`vet-jobs.js`): a new
     `content_verified` / `content_issue` pair is required in every per-job schema response,
     with an explicit hard-stop instruction warning that length is not a proxy for real
     content. When `content_verified` is false, the assembler blanks ALL four sub-scores and
     the final score (not just the final one — a lingering sub-score can still look
     legitimate), forces `status` to `"⚠️ NEEDS RE-FETCH — content not verified"`, and sorts
     that row to the very top of the rankings so it can't be missed.
  3. **The spreadsheet flags it loudly** (`make_rankings_xlsx.py`): a row with that status gets
     a jarring magenta fill across the ENTIRE row — not just the Status cell — overriding every
     other per-cell color, since none of a bad row's lane/comp/location data is trustworthy
     either.
- **Retroactively verified** all 12 files in the 07-16-26 batch and all 91 in the 07-14-26
  rescore project against the fixed check — no other silent failures found in either.
- **Also fixed in the same pass** (found while investigating the batch): the Lane column now
  colors by health-domain only (bright green for "Health - Mental Health", lighter green for
  other Health subcategories, no green outside Health — was previously colored by
  lane-priority-match, which is a different question); lane text is now normalized to the exact
  string "Health - Mental Health" (schema + prompt + a deterministic post-processing
  normalizer); a Working-Location parsing bug where "NYC/SF - 3 days" (missing the "IRL"
  prefix) fell through to "Unclear" instead of "Home hybrid"; and `make_rankings_xlsx.py` never
  actually got the left-alignment fix applied earlier this week to the *other* project's
  one-off script — it only ever touched `build_rescore_workbook.py`, never this shared engine
  file, so every ongoing batch kept the old center-aligned columns until now.

## 2026-07-16 — Fixed a syntax bug that silently broke `run-batch` and `vet-jobs`

- **Symptom:** `run-batch` failed immediately with `Error: workflow('vet-jobs'): no workflow with that name`
  — even though `.claude/workflows/vet-jobs.js` existed on disk with the correct `meta.name`. Calling
  `vet-jobs` directly by name also failed as "not found," and only when invoked via `scriptPath` did the
  real error surface: `Script parse error: Unexpected token (64:857)`.
- **Root cause:** an unescaped apostrophe in a schema description string inside `vet-jobs.js` (`"...in
  the candidate's preferred order..."`) closed the single-quoted JS string literal early, breaking the
  whole file's syntax. A workflow file that fails to parse is silently dropped from the runtime's
  workflow registry rather than surfacing a parse error at discovery time — which is why the failure
  first showed up as "no workflow with that name" instead of a syntax error.
- **Fix:** escaped the apostrophe (`candidate\'s`). Verified with `node -c` and by successfully running
  the workflow end-to-end afterward.
- **Context:** discovered while running the 07-16-26 batch (12 URLs pasted into the inbox, 9 fetched
  cleanly — Pinterest and Meta both 403/400'd, Feeld came back too thin at 29 chars, no Playwright
  installed to auto-retry). Vetting, on-ice overlay, and tailoring the top 5 non-on-ice jobs all ran
  successfully against the fixed file.

- **The change.** ChatGPT's second review identified the largest remaining variance source correctly: "is this
  central thesis-defining or merely supporting?" carried enormous weight (only thesis-defining centrals set
  bands) with one sentence of guidance. Added **Step 1c — the Hiring Thesis Test**: four questions (Identity /
  Repetition / Interview gravity / Failure test), decision rule "thesis-defining only when the overall evidence
  strongly supports it; when uncertain, prefer supporting," plus the **core identity ≠ necessary competency**
  distinction. Also **tightened the compounding clause**: two weak thesis-defining centrals compound only when
  genuinely *independent* facets, never when they're one gap named twice. Public template updated in lockstep.
- **One design decision not in the spec: Step 1c runs BEFORE Step 2 grading, and the classification may not be
  revised once grades are visible.** Without that ordering "prefer supporting" becomes a one-way ratchet — a
  scorer seeing `absent` has every incentive to reclassify the requirement as supporting, and the rubric quietly
  stops penalizing anything.
- **⭐ The result that matters: the user's eye was right and the rule change reproduced it.** She called Fetch and
  Peloton "probably in the sixties" by eye, three rubric versions ago. **Fetch 97→70→47→67. Peloton 79→62→44→65.**
  Two agents found it independently, without knowing the target, both identifying that each posting names ONE gap
  from three angles. This is the only external calibration signal the system has ever had, and V2.1 hit it.
- **Canary duplicate control: 1 pt (41/40) — the best ever measured** (V1 = 0 but on a different framing; V2 = 3).
  The V2 residual is closed: it had traced to a duration-qualified central ("3+ years native mobile"), and
  classifying before grading made both agents reproduce the card's own worked example and converge.
- **Net effect ZERO — redistribution, not inflation.** −21 pts across 71 rows (−0.3 mean), yet 19 rows moved ≥8
  pts and chunk nets swung +38/+9/−22/−23 and cancelled. **82+ concentration fell 59% → 54%**, addressing the
  inflation concern without anyone targeting it.
- **⚠️ I predicted this wrong and it's worth recording why.** I forecast V2.1 would push scores UP and worsen the
  concentration, reasoning "prefer supporting → fewer downward band-setters → higher scores." Missed mechanism:
  Step 1c forces scorers to *justify* thesis-defining status, which **promotes centrals as often as it demotes
  them** (Faire −22, Oura −28, Stitch Fix −23 all fell under a rule I expected to be one-directional).
- **⚠️ Methodology bug I introduced: the `v21_delta_note` I asked each agent for is confabulated and unusable.**
  Chunk 4 reported "9 of 14 rows moved upward, typically +12 to +20"; actual movement vs the real V2 run was 3 up,
  7 down, net −22. **Every agent invented a "naive mechanical read" baseline no scorer produced, then credited the
  rule with the difference.** Lesson: a model asked to estimate its own counterfactual fabricates a strawman and
  scores against it. Only a real A/B diff is evidence. Discarded.
- **⚠️ Real bug I introduced: Step 1c broke the `<30` credential band.** Meta's "BA/BS in Computer Science" fails
  all four Hiring Thesis Test questions (not the identity, mentioned once, no interview gravity, an excellent
  candidate succeeds without it) → classified supporting → cannot set the band → Meta should be ~55. But the
  `<30` row names "CS degree *required*" as its own worked example. A scoring agent caught the collision, resolved
  for the credential row (28), and flagged it exactly right. **Credential gates operate at the application, before
  any thesis reasoning exists — a different mechanism, wrongly routed through a capability test.** Fix identified
  (exempt hard credential/history gates from Step 1c); NOT applied — calibration run.
- **The remaining variance moved from classification to GRADING.** Oura (76→48), Stitch Fix (69→46), Faire
  (74→52) each moved ~25 pts with no rule touching them: agents agreed on the band-setter and disagreed on where
  in the band an `absent` thesis-defining central lands. Step 1c tells you *which* central sets the band; nothing
  tells you *where in the band*. Largest measured disagreement now.
- **Pressure point for the freeze decision:** Everyday Health's SEO ask passes 3 of 4 tests and fails Repetition
  outright (one bullet, absent from responsibilities). Thesis-defining → 42; supporting → ~85. **43-pt swing on
  one call**, and the decision rule points both ways. The test concentrated variance from many small judgments
  into one big explicit one — progress, but it needs a tie-breaker.
- Both workbooks rebuilt. Full report: `1 - Rankings/V2.1-calibration-report.md`. V2.1 is a candidate baseline
  pending review — not adopted.

---

## 2026-07-15 (later) — Formatting fixes in workbook builder + lane taxonomy corrected

- **Lane formatting: hyphens instead of middle dots.** The lane taxonomy was outputting "Health · Mental
  Health" instead of the spec'd "Health - Mental Health". Fixed the payload data (all 71 rows) and
  rebuilt both workbooks with the corrected format. Going forward, lane fields will use hyphens.
- **Column alignment: text columns left-aligned.** The main ranking workbook was centering all columns.
  Fixed `build_rescore_workbook.py` to left-align Lane, Company, Job Post Title + Link, and Working
  Location (columns 3–6), while keeping scores and other data centered. Both workbooks rebuilt.
- **Root cause:** Lane mapping was using middle dots as hierarchy separators; the workbook builder had
  no awareness of text vs. numeric columns. Fixes applied directly to payload and the builder script.

---

## 2026-07-15 (calibration run) — V2 rescored all 71 blind; duplicate control passed at 3 pts; top-band concentration got worse, not better

- **The run.** 5 blind agents, 14–15 jobs each, reading only the revised card §2 and profile PART 1. V1
  scores snapshotted first and never shown to any scorer; agents instructed not to anchor and not to
  shape the distribution. Full report: `1 - Rankings/V2-calibration-report.md`.
- **Canary duplicate control PASSED at 3 pts** (rows 3/51, MD5-verified identical, different chunks,
  different agents): 36 vs 33 on Profile Fit, 55 vs 52 on the final. Both agents landed the same band,
  the same band-setter, and the same coherence call — the reasoning converged completely.
- **The residual 3 pts found a real rule gap, which is the run's most useful output.** It traces to one
  grade call on identical Kngroo evidence (`direct (thin)` vs `light`) against a central carrying a
  **duration qualifier** ("3+ years native mobile"). The 7/15 fix says grade `direct` from evidence
  alone without requiring recurrence — but is silent on evidence measured against a requirement that
  *itself* demands sustained duration. Both readings are defensible under the current text. **Highest-
  value fix available; not applied (calibration run, no architectural changes).**
- **The fix-#1 evidence/coherence split is demonstrably working**, produced independently by three
  agents. Best proof: **Paperless Post 97 vs Fetch 47 — same underlying evidence (her invite-loop
  work), scored by the same agent in the same chunk, credited at one and refused at the other**, with
  the distinction stated in a line (invitation *sending* is what she owned; a rewards/incentive engine
  is not). Two agents stated the counterfactual arithmetic unprompted — Faire: *"grading the evidence
  and the coherence separately is what puts this at 74 rather than either ~88 (evidence-only) or ~50
  (coherence folded into the grade)"*; Alloy: *"a pre-split reading would have graded this materially
  lower."*
- **The Step 3 guardrail (fix #4) drove most of the large increases** by correctly demoting domain and
  spike requirements to company *context* or explicit bonuses: Talkspace 65→87 (mental health is
  context; the thesis is onboarding/activation), Prava 66→87 (posting labels healthcare "Bonus" →
  Rule B forbids gating), Figma 79→92 (every design-tools spike is explicitly "not required"), Stitch
  Fix 34→69, Oura 46→76. V1 had been letting bonus items and context do centrals' jobs.
- **⚠️ Honest negative result: the 82+ concentration ROSE from 52% to 59%.** ChatGPT's "is the scale
  still inflated" concern is now more pronounced, not less. Two readings, and this run cannot decide
  between them: (a) the bands changed meaning — V1's 82–96 claimed "comfortably shortlisted" (a pool
  claim), V2's claims "the career tells this story convincingly" (narrative only, a weaker and more
  defensible assertion), and these are jobs she self-selected as career-matching; or (b) residual
  leniency the rewrite didn't fix. **What did clearly improve: separation** — stdev 17.5→18.8, the
  68–81 middle hollowed out (12→7) while the tails filled (30–49: 7→9). Resolving (a) vs (b) needs
  real application outcomes, not another rubric pass.
- **⚠️ Flagged for the user, not silently accepted: Fetch (47) and Peloton (44) are now materially
  BELOW her stated intuition** ("probably in the sixties" for both). Trajectories: Fetch 97→70→47,
  Peloton 79→62→44. Suspected cause: the guardrail's **compounding clause** may over-penalize when two
  weak centrals are two facets of the *same* specialization rather than independent gaps. Candidate fix
  identified, not applied pending her judgment.
- **Five pressure points documented, no rubric changes made** (per the run's terms): duration-qualified
  centrals (above); postings that file one capability as both requirement and bonus (Adobe); whether
  narrative softeners can move a band or only position (Headway); **no mechanical test exists for
  "thesis-defining vs supporting"** — now the highest-leverage judgment in the dimension and worth ~18
  pts on a single posting alone, with one sentence of guidance; and Alignerr (Profile Fit 97 / Desire 18)
  as the known "top of a weak pool" blind spot — behaving *correctly*, flagged so it doesn't get
  "fixed."
- Both workbooks rebuilt. V2 is a candidate baseline pending review — not yet adopted.

---

## 2026-07-15 (even later) — Four logic bugs fixed in the hiring-thesis rewrite before the rescore ran

- **A second round of ChatGPT review, this time on the hiring-thesis rewrite itself, caught four real
  bugs before any of the 71 jobs were rescored under it.** All four accepted and fixed in
  `01-scoring-card.md` §2:
  1. **`direct` was defined too narrowly.** It required the evidence to *also* connect to a career
     throughline, conflating "did she do this" with "does her career repeat this pattern." That would
     force real direct experience (e.g. Kngroo's native-iOS ownership) down to `transferable` just
     because mobile isn't a throughline. Split into two separate judgments: `direct` is graded from
     the evidence alone; a new **narrative-coherence** step (after Step 2) handles repetition
     separately — it can move her position within a band, or cap the band's ceiling on a role whose
     thesis explicitly requires sustained specialization, but it never changes whether one example is
     `direct`.
  2. **The candidate profile contradicted itself about what counts as a gap.** "Only these six items
     are gaps" directly conflicted with the card's own instruction to grade an unlisted, clearly-
     required specialization `candidate-silent` → `absent`. Renamed the section **Confirmed Recurring
     Gaps and Boundaries** and rewrote its rule: the list covers gaps confirmed during intake and
     likely to recur across many roles — it is explicitly NOT exhaustive, and a per-job `absent`
     finding on an unlisted specialization is a job-scoped evidence judgment, not a new permanent
     claim, and must not be added to the list or reused on a different job with a different thesis.
     Same fix applied to the public template so future users don't inherit the contradiction.
  3. **Rule B smuggled the fabricated applicant pool back in.** "Covering 0-of-N is direct evidence
     that better-matching careers exist" is an inference about hypothetical other candidates — exactly
     what the rewrite was supposed to remove. Reworded: the deduction is earned by her own profile's
     incompleteness against the posting's stated ideal, not by a claim about who else applied.
  4. **"The weakest central sets the band" had no guardrail against a secondary item dominating.** Added:
     before a central can set the band, it must be verified as **thesis-defining** (part of the Step 0
     identity), not merely a supporting requirement that happens to pass the Centrality Test. A weak
     supporting requirement moves her position within a band; only a weak thesis-defining central can
     force a lower band. Tightened the sanity check to require naming *why* the gap undermines the
     hiring story, not just that it appeared in the requirements section — this is what stops Cloaked's
     secondary "read code when useful" ask from overpowering its explicit retention/engagement thesis.
- **Two smaller, accepted profile refinements** in `02-candidate-profile.md`: throughline #2 renamed
  "Onboarding, activation, and helping people become more capable," with a line naming that it shows up
  in hiring/mentoring/career development/community-building/Ascend, not just product activation —
  the prior wording underplayed the human-development thread relative to what's actually documented.
  Throughline #6 (community/founder ecosystems) changed from "never the headline" to "supporting in
  most roles; potentially central when the hiring thesis itself concerns smaller organizations,
  community-led growth, founder enablement, or nonprofit capacity-building" — closer to the evidence
  without licensing every incidental "community" mention to inflate a score.
- **What was reviewed and rejected:** nothing — all four scoring-card fixes and both profile
  refinements were assessed as correcting real logic errors (verified against the actual file text
  before editing, not taken on faith) and applied as proposed. No open-ended rewrite beyond these six
  changes, per the reviewer's own recommendation not to risk bloating a structure that's otherwise
  sound.
- The 71-job rescore still has not run. This was a second, necessary correction pass before it does.

---

## 2026-07-15 (later) — Profile Fit rewritten around "hiring thesis + narrative coherence"; pool-ranking retired same day it shipped; candidate profile becomes a reasoning document

- **Where this came from.** The user took the scoring system to ChatGPT for an independent second
  opinion and came back with an architectural revision, which survived review here with guards
  added. Core critique accepted: the pool-ranking frame (shipped earlier today) had the scorer
  estimating percentile rank in an applicant pool it has never seen — confident-sounding
  fabrication. The dimension (formerly "Market Perception," now **"Profile Fit — how they see
  her"**; CSV field and spreadsheet column names unchanged) now asks: **how strongly would this
  company perceive the documented career as matching the person they're trying to hire, from
  application through interviews?**
- **The conceptual shift: narrative coherence over requirement checklists.** Scoring starts by
  stating the role's **hiring thesis** (ledger row zero — what kind of person is this company
  actually trying to hire, the identity behind the title). Rule A recast from "the specialization
  the role is NAMED for" to "the hiring thesis is always central" — the title is evidence of the
  thesis, not the thesis. Repeated career themes (throughlines) earn narrative credit; one isolated
  analogous bullet does not. New **interview test**: a grade must survive "tell us about the X
  you've built." New mandatory **misclassification check** against the profile's new Common
  Misclassifications list (invitations ≠ referral programs, notification system ≠ ESP execution,
  AI builder ≠ production AI shipper, …).
- **`unknown` split in two; the 68 floor deleted.** `posting-ambiguous` (vague posting) = neutral,
  cannot set the band. `candidate-silent` (posting clearly asks; profile has no named evidence) =
  runs the name-the-evidence test honestly, usually `light`/`absent`, plus a logged question for
  the user. The old single `unknown` with its "may never set a band below 68" floor manufactured
  optimism exactly where a recruiter would see a hole.
- **Kept, deliberately, against the grain of the rewrite:** the whole mechanical skeleton — ledger,
  Centrality Test with hard cap 6, evidence-grade definitions, name-the-evidence test, one-concern-
  one-deduction, Rule B (bonuses rank, never gate; no bonus section = neutral), Rule C (no upward
  tie-break, now phrased via the interview test). Reason: this session repeatedly measured that
  holistic judgment does not reproduce (29-pt spread on the byte-identical Canary control) and
  mechanical structure does (spread 0). "Narrative coherence" is *more* holistic, not less; the
  skeleton is what keeps it honest. **The Canary duplicate-row control remains the acceptance test
  for the upcoming rescore: >~3 pts of spread on Profile Fit = the wording failed, iterate before
  accepting any numbers.**
- **`02-candidate-profile.md` restructured from biography to reasoning document:** Career Identity →
  Career Throughlines → Clearly Established Strengths → **Adjacent Experience** (real experience
  that is NOT a defining specialization: mobile, growth, healthcare, production AI, enterprise,
  marketplaces, SMB) → Genuine Gaps → **Common Misclassifications** → seniority/education → compact
  Career History. The PART 1 evidence / PART 2 preferences wall survives untouched. Throughlines
  were verified against the experience-bank/positioning canon before inclusion (community/founder-
  ecosystem work is documented there; "nonprofits" was in the user's ChatGPT discussion but has no
  documented evidence, so it was left out).
- **Public templates updated in lockstep** (`02-candidate-profile.template.md` restructured to the
  reasoning-document shape; `01-scoring-card.template.md` §2 + Fit fair-scoring rules rewritten to
  hiring-thesis/narrative framing, two-kinds-of-silence, bonus-rank rule) so a future `/intake`
  run generates the new structure for any user. Templates stay generic.
- Full 71-job rescore under the new rubric is pending the user's review of the two rewritten
  private files (deliberate hard stop — a wrong self-description in the profile would poison all
  71 scores).

- **The problem the user named.** Reviewing the rescored batch, she didn't trust Market at all:
  Fetch 97 despite the posting explicitly wanting someone who'd built referral programs, Cloaked 98
  despite an explicit "can read real code" ask, Peloton 79 despite 0-of-5 bonus items. Her framing
  is the fix: a recruiter isn't checking whether she clears a bar, they're stacking her against the
  other resumes in the pile. **Market now asks "where does she rank in the applicant pool," not
  "does she satisfy the requirements."** Both band tables reworded accordingly: 97-100 top handful /
  82-96 comfortably shortlisted / 68-81 gets a look but better-matched candidates exist / 50-67 needs
  a referral / 30-49 likely screened out / <30 credential gate.

- **Three rules added, because the reframe alone wasn't reproducible.**
  - **Rule A — a named specialization in the title or spine is always central, and it cuts both
    ways.** It's what most rescored the batch. Up: Paperless Post 95 (its "Send and Manage" spine
    *is* the notification system she owned), Cloaked 95, Clio 92. Down: EllieMD 42 (a hardware
    spine she has nothing for), Stitch Fix 34, Fetch 70, Hims & Hers 80.
  - **Rule B — bonus/preferred sections rank but never gate; no bonus section = neutral.** Prevents
    a posting that simply doesn't list nice-to-haves from being scored as though she failed them.
  - **Rule C — no upward tie-break.** Deliberately deleted the tie-break added earlier the same day.
    Worth being precise about why, since it looks like a reversal: "omission ≠ absence" and
    "imperfect ≠ implausible" govern how you read *her profile* and still stand. Rule C governs how
    you rank her against *other applicants* — and against a real pool, ties don't break her way.

- **The evidence, captured because the trial predicted it.** Fetch 97→70, Cloaked 98→95, Peloton
  79→62 — all three landed where the user said they should sit by eye.

- **The Canary control (rows 3 and 51: same URL, byte-identical files, scored blind by two agents)
  held at spread 0 on Market — 42 vs 42.** Both agents independently graded the SDK requirement
  `absent`; the upward tie-break had been the only thing holding it at `light`/62. The framing change
  moved the control 20 points *in unison*, which is what a genuine rule change should look like as
  opposed to noise. Full-score spread on the control is 2 points (57 vs 55).

- **Methodology note worth keeping: chunk-mean spread is not a variance measure.** Mid-run I nearly
  reported an "18.9-point agent-to-agent spread" as a calibration failure. It was composition, not
  bias — the chunks hold different jobs, and the high chunk contained Asana (literally her former
  product) while the low chunk held Meta, Stitch Fix, and Canary. Only the duplicate-row control
  compares two agents on identical input. **Don't infer scorer disagreement from statistics over
  non-identical samples.** Related earlier lesson, same failure family: I prematurely declared the
  ceiling model broken on 4 of 5 chunks when the missing chunk held the decisive control.

- **Known blind spot, not fixed.** Market rewards "top of a weak pool" identically to "top of a
  strong pool" — Alignerr scores Market ~98 with a Desire of 18. A high Market is a statement about
  her odds, not about whether the job is worth wanting. The weighted final (Desire 35%) is what
  absorbs this, but the Market column read alone will mislead.

- Batch result across 71 rows: Market 27-98 (mean 76.6, was 82.7 under the ceiling model);
  final 46-91 (mean 73.1). The 50-75 middle no longer clusters.

---

## 2026-07-14 (evening) — De-anchor fix was incomplete; comp-band coloring semantics questioned

- **The earlier same-day de-anchor fix missed 5 rows.** The list of "companies named in the scoring
  card" was built from memory of the anchor tables rather than by systematically extracting every
  proper noun from the file, so the keyword search omitted `playlist`, `google`, `asana`, and
  `justworks`. The fix was reported as covering "10 affected rows"; it should have been 15. Caught
  only because the user flagged that Mindbody's Desire (32) and Market (55) were obviously wrong.
  **Lesson: when auditing "everything matching a pattern," extract the pattern set from the source
  file programmatically — never enumerate it from memory, and never report a count that came from a
  hand-built list.**
- Rescoring the 5 (Playlist ×2, Google, Asana, Justworks) produced the strongest evidence yet that
  the de-anchor fix is correct: the two Playlist rows — same company, same brand — now sit **30
  Desire points apart** (Founding AI PM 88 vs. Professional-Services Lead PM 58), because the rubric
  now scores the role rather than the logo. Mindbody's Market went 55 → 78 once the card's own
  Profile-Fit protections (count one gap once; "plus"/"ideally" is not a day-one gate) were actually
  applied.
- **Open engine question — comp band semantics.** `make_rankings_xlsx.py` already color-codes the
  Comp Range column for all users (good), but `compFitLabel()` in `.claude/workflows/vet-jobs.js`
  classifies the band using `max(range)`, so a posting of `151-201` against a 180 floor / 200 target
  paints **green ("meets/above target")** even though the midpoint (~176) is below the floor — a
  green cell directly contradicting a "below floor" note. The one-off rescore workbook now uses a
  stricter midpoint rule (green only if midpoint ≥ target; red only if max < floor; yellow for
  straddles). Not changed in the shared engine because it affects every user — needs a decision.

## 2026-07-14 (later still) — Location color/score derived from the posting instead of the authoritative spreadsheet (batch bug + general lesson)

- The user spotted a row (Prava Therapy) whose Working Location cell said "Remote" but was
  colored red with a Comp+Lifestyle score of 22. Root cause in the one-off
  `build_rescore_workbook.py` / rescore flow: the scoring agent decided `location_tier` (the
  cell color) and the location component of practicality from its own read of the **job
  posting**, instead of from the candidate's **authoritative spreadsheet** Working Location —
  violating the historical-rescore source-of-truth rule ("spreadsheet wins for location, never
  overwrite it"). It failed both ways: remote/home-metro rows shown as penalized (Prava,
  Everyday Health, Thoughtly), and in-office NYC rows shown as green/remote (Biograph, Playlist,
  Forus, Faire, Gaia Family).
- Fix (batch outputs only, not shared engine): `location_tier` is now derived deterministically
  from the sheet's Working Location text by one rule (Remote→green; NYC 1–2 days→yellow; NYC
  3+/unclear/multi-hub→orange; non-NYC required→red) for all 71 rows — 17 colors corrected.
  Practicality re-scored for the 3 rows whose location itself was mis-scored (Prava 22→78,
  Everyday Health 15→48, Thoughtly 35→68). Detail in that batch's `1 - Rankings/QA-report.md`
  (draft 6).
- **General lesson for the engine:** a color/tier classification like this should be computed
  deterministically from the normalized location string, never decided by the LLM — the LLM
  conflated "great fit for her (NYC home base)" with "remote-first (green)". The real engine
  already does this correctly (`make_rankings_xlsx.py` maps deterministic `locationFitLabel`
  output → color); the bug was only in the one-off rescore workbook builder, which had let the
  LLM choose the tier. Worth guarding against if `location_tier`-style LLM fields are ever added
  to the shared path.

## 2026-07-14 (later) — Named-company scoring-card anchors found outside Market Perception and fixed; resolves the original Knit mystery

- While rescoring Spring Health against real posting text supplied by the user, found that
  `PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/01-scoring-card.md` still named
  specific companies directly as scoring anchors in the **Desire tier table, Company Style anchor
  table, and Practicality anchor table** (e.g. "Company Style 45–61 = Spring Health," "Desire Tier 3
  = Knit," "Practicality 96 = Skylight"). The earlier same-day migration audit had fixed this exact
  bias pattern in the Market Perception table only — this is the identical failure mode (a score
  reproducing because the rubric names the company in that band, not because of the posting's actual
  content), just missed in three other tables.
- All named-company language was scrubbed and replaced with abstract evidence patterns, matching the
  style already used for Market Perception. 10 already-scored rows in the in-flight historical
  rescore batch had their company named in one of these tables (Spring Health, Oura, Headway,
  ClickUp, Kindred, LTK, Knit, Meta/Instagram, BetterUp, Peloton) and were rescored fresh against the
  fixed rubric.
- **This resolves the original mystery that started the whole migration audit**: Knit's score moved
  from 53 to 74 (+21) purely from removing its own named anchor — strong evidence the original
  58→38 drop was a real, structural scoring-card bug affecting every named company in these tables,
  not something specific to Knit. Full before/after detail in
  `__READY_TO_REVIEW__PRIVATE_GITIGNORED/07-14-26 RESCORE ALL THE JOBS!/1 - Rankings/QA-report.md`.
- Separately, two of the historical rescore's 5 "posting taken down" reverts (Spring Health, Hone
  Health) turned out to be wrong: the user supplied the actual saved posting text directly, proving
  the automated fetcher was blocked, not that the jobs were gone. Take "fetch returns nothing" as
  "couldn't retrieve," not "doesn't exist," when a user-supplied copy is available to check against.
- Same pattern closed out the last 3 gaps: the user supplied real posting text for Clio (fetch had
  genuinely 403'd), Skylight (fetch hit a JS-rendered page and got nothing, no Playwright available),
  and Adobe/Design at Adobe (fetch actually succeeded both times but landed on a real "this job has
  been filled" notice — a genuine closed-posting signal, unlike the Spring Health/Hone Health false
  alarms). All 71 rows in the historical rescore batch now have live, verified scores; zero remain
  reverted to a historical/unavailable placeholder.

## 2026-07-14 — Migration audit fixes shipped; historical rescore test found and fixed a serious fuzzy-matching bug

- Root cause of the Knit job's old-vs-new score drop (58→38 on Market Perception) was
  audited rather than assumed: found the candidate profile file had drifted/thinned
  during the deprecated Job Pipeline → JAIL migration, the scoring card had named-company
  anchors and a duplicate/contradictory band-cutoff table, and lane taxonomy had gone
  free-form. Fixed all three: rebuilt `PRIVATE__YOUR_FILES_GITIGNORED/
  03-VETTING__YOUR_PRIVATE_INFO/02-candidate-profile.md` (evidence vs. preference
  sections split, restored dropped details like 0→1/founder history, hands-on AI
  building reframed as strength not gap), consolidated the scoring card to one band
  table with general fair-scoring protections (day-one-gate-vs-learnable, count-gap-once,
  omission≠absence), and constrained Lane to a `<Bucket> - <Subcategory>` pattern in
  `.claude/workflows/vet-jobs.js`. Equivalent general (non-personal) guidance was mirrored
  into the public `.template.md` files and `.claude/skills/intake/SKILL.md` so future
  users get the same protections without any Jessica-specific data leaking into templates.
- Workbook column layout became dynamic instead of hardcoded: `make_rankings_xlsx.py`
  now reads a per-run `<batch>-rankings.meta.json` (written by `vet-jobs.js`) for score
  labels/weights, and the 24-column layout was reordered to an exact requested order
  (contiguous score block, `Base Resume Used` added, deprecated `ClaudeStatus`/lane-dupe
  columns dropped). `resolve_submitted_applications_link()` was simplified from
  directory-scanning to reading one explicit `archive.current_year_path` config value.
- Location handling fixed: NYC/SF abbreviated everywhere (general); Jessica's multi-city
  postings now order by an explicit `location.city_priority` list in `jail.config.json`;
  a bug where `"IRL NYC - unknown days"` was mis-resolving to `"Unclear"` (the
  unknown-substring check ran before the IRL/onsite check) was fixed. Added a Lever
  fetcher and a generic schema.org `JobPosting` JSON-LD fallback to `ats_fetchers.py` for
  non-ATS sites, used by both the sync and Playwright prep scripts. Added a first-run
  completeness nudge so a new user's first vetting pass warns if `jail.config.json` is
  missing comp/location/lane info instead of silently scoring against gaps.
- **Historical rescore test** (71 real historical job rows, run as a one-off validation
  against the fixed engine): surfaced a serious bug in my own local-file-matching logic,
  not the engine. A fuzzy company+title matching fallback (used when no exact filename/
  URL match existed) was checked at low confidence scores first, found wrong, and on
  digging further **all 33 fuzzy matches at every confidence level (2 through 5) turned
  out to be wrong** — including the batch's single highest-scoring row. Every match was
  re-verified by comparing the candidate file's own `URL:` header against the row's real
  hyperlink (the only reliable method found); 28 of 33 were corrected via real re-fetch,
  5 were genuinely unavailable (postings taken down or bot-blocked/JS-rendered) and
  reverted to their original historical scores rather than guessed at. Full account,
  including a related "plausible placeholder score" schema loophole (an agent returning
  a fake-but-in-range 50/50 instead of an honest 0 when a file couldn't be read) and a
  large-JSON read/write truncation failure mode in the Workflow harness (fixed by
  chunking), is in `__READY_TO_REVIEW__PRIVATE_GITIGNORED/07-14-26 RESCORE ALL THE JOBS!/
  0 - Prep Report/prep-report.md` and that batch's `1 - Rankings/QA-report.md`.
  Conclusion for future engine work: never ship a fuzzy-match fallback without a
  mandatory content/URL verification step — score-level plausibility alone gave no real
  signal of match quality.

## 2026-07-13 — Changelog capture became mandatory, synthesis lost its API dependency

- `CLAUDE.md` now requires every coding agent — Claude Code, Codex, or otherwise — to
  add a rough `docs/changelog.md` entry in the same turn as any meaningful change, or
  state why none is needed. This was previously only a soft pointer, not a completion
  requirement, and rough entries were not being captured automatically as a result.
- Added `AGENTS.md` so Codex finds the same rule without a duplicated copy.
- Removed the direct Anthropic API call from `scripts/doc_synthesis.py`. The original
  design assumed unattended, standalone synthesis (mirroring an external reference
  implementation), but the actual workflow asks an active Claude Code or Codex session
  to perform synthesis itself. The script now only gathers Git evidence and manages
  the deterministic structure/marker; no API key is needed anywhere in this repo.
- The private Writing home this repo symlinks canon from was reorganized (see its own
  git history) — three symlinks under `PRIVATE__YOUR_FILES_GITIGNORED/
  04-TAILOR__YOUR_PRIVATE_INFO/` were repointed to match: the two Ascend canon files
  and `cover-letter/writing-links.md`. Verified with a real lint run through the
  updated symlink chain — resolved and read cleanly, no path errors. The other 12
  symlinks in that folder were unaffected (their targets didn't move).

## Pre-2026-07-13 — Everything before the changelog existed

- JAIL shipped its V2 pipeline (Prep → Vet → Tailor → Reconcile/Archive) and the
  three-root layout (`ENGINE__PUBLIC_GIT_TRACKED` / `PRIVATE__YOUR_FILES_GITIGNORED` /
  `__READY_TO_REVIEW__PRIVATE_GITIGNORED`) before this changelog began. See
  `docs/v2-end-to-end-workflow.md` and `docs/testing-and-caveats.md` for that history.

## Earlier — Origins

- The project began as a single-purpose resume tailoring helper and grew into the full
  chained pipeline described in `README.md`.
