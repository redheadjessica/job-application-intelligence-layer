# Process retrospective — 2026-07-30

Written after the largest continuous work stretch in this repo's history (the capture-format
migration, the 27-column tracker contract, a full batch refresh + rerank, and two application
packages). Roughly 25 real defects were found and fixed across ~20 commits. This doc is the
"senior CTO" pass over that history: why the bugs kept coming, what tech debt actually exists,
and an ROI-ranked plan for making future work faster and less bug-prone. No code changed as part
of this write-up.

## 1. Root-cause taxonomy — where the ~25 bugs actually came from

Every defect from this stretch fits one of five classes. Counting them changes what's worth
fixing: the classes are NOT evenly sized.

**Class A — duplicated code paths that evolve independently (5+ bugs, the worst class).**
Two prep CLIs each carried their own `fetch_one`; an enrichment landed in one and not the other,
and unit tests passed against the copy the real pipeline never calls. The same shape appeared as
mirrored constants (wrapper patterns in two modules), a JS/py pair of normalizers, and a
column-list defined in test helpers. *Every* instance eventually diverged. Partially fixed
(shared choke-point enrichment + a behavioral divergence test), but the two CLIs still exist.

**Class B — LLM-owned output treated as a contract (6+ bugs).**
Prompt-instructed formats drifted: the missing `IRL` prefix, miscased status values, two
different resume-filename spellings in the same run, rationale prose written into a
machine-owned column. The repo's core lesson held every time: a format enforced by prompt is a
suggestion; a format enforced by a post-model normalizer is a contract. Nearly all of these are
now mechanical — the remaining LLM-owned surface is the scorer's row assembly (one malformed row
in 55 this run: a returned object lost two fields on the way into the CSV, caught only by QA).

**Class C — tests green while the artifact is wrong (4 bugs, most dangerous).**
A vacuous regression test that passed against the unfixed code; unit tests exercising a function
the live path didn't call; registry-correct data rendered wrongly into the visible file; a
byte-pinned golden fixture that couldn't see a path not wired to it. The fix that worked was
testing the FINAL artifact (written cell hex, written file, both CLIs behaviorally) — every time
that standard was applied, the bug class died.

**Class D — silent failure (4 bugs).**
A partial prep run silently wiped other jobs' manifest entries; the tracker writeback no-op'd
while the workflow reported success; a crashed rebuild script once led to verifying stale data;
an exception swallowed by a bare `except` hid that JSON-LD extraction had never worked. Policy
now in force — loud-or-fail — but it must be applied at every new integration point by default,
not retrofitted.

**Class E — spec evolution mid-flight (not a code defect, but the biggest schedule cost).**
The capture format went through three approved revisions; the column contract replaced names and
semantics late. This is healthy product iteration, but each revision invalidated pinned tests
and golden fixtures, which is exactly why the stretch *felt* slow. The end-state process —
write the full contract spec first, audit consumers read-only, then one atomic migration —
was dramatically cheaper than the incremental path taken earlier.

**On the "is it the multi-user design?" question:** mostly no. The generic/personal split added
two real frictions — candidate-relabelable score columns vs. a fixed header contract, and the
privacy firewall occasionally blocking commits (each time correctly). But classes A-D would
exist in a single-user codebase. The honest driver of bug volume was that this stretch touched
every extraction path against live, adversarial inputs (five ATSes plus employer pages), and
live inputs kept finding what synthetic fixtures couldn't. The honest driver of *slowness* was
Class E plus the fix→refetch→inspect loop being manual.

## 2. Current tech-debt inventory (verified, not vibes)

1. **Two prep CLIs** with duplicated `fetch_one` scaffolding (Class A residual). Shared logic
   is centralized and guard-tested, but the duplication invites the next divergence.
2. **Scorer row assembly is unvalidated** — nothing checks each CSV row for integrity (job-file
   resolves, required cells non-empty, label domains) before the file is written. One row in 55
   was malformed this run and only end-of-day QA caught it.
3. **Board-token company naming** on ATS-hosted URLs has no employer-name source (the
   employer-page lookup deliberately skips ATS hosts), so run-together/miscased brand names can
   land in captures. Two instances in the current 55 (cosmetic, but trust-eroding).
4. **The capture acceptance gate exists only as an ad-hoc script** rewritten by hand three times
   during this stretch. It caught real bugs every time it ran; it lives nowhere.
5. **No end-to-end pipeline test.** 537 unit/contract tests, zero tests that run
   fetch→normalize→rank-assemble→xlsx as one flow on stubbed inputs. Every wiring bug this
   stretch (writeback no-op, batch routing, CLI divergence) lived between units.
6. **Golden-fixture churn**: byte-pinned goldens needed regeneration on nearly every format
   commit. Correct behavior, but each regeneration is a manual judgment moment.
7. Minor: mirrored wrapper-pattern constants (drift-pinned by a test, acceptable); one stray
   non-English word in a pushed commit message; staging/backup folders accumulate in the private
   tree and rely on convention for cleanup.

## 3. The plan, ranked by ROI

### Tier 1 — high value, low cost (recommended; ~1 day total)

| # | Change | Cost | Why it pays |
|---|---|---|---|
| R1 | **Promote the capture acceptance gate into the engine** (`02-PREP/qa_captures.py`): section order/presence, canonical filename, required fields, no blank posted date, body length + structure, fusion guard, question-filter screen, no legacy markers, ORIGINAL/LATEST sanity. Run automatically at the end of every prep run and print a per-file verdict. | ~2h | This exact checklist caught real bugs all three times it was run by hand. Zero-cost to run; converts "QA pass at the end" into "gate on every fetch". |
| R2 | **Row-integrity validation in the post-scoring normalize pass**: every row must have a resolving Job File, non-empty Lane Fit when Lane is set, and label-domain-valid Comp Fit / Data Completeness / Status; violations repair-from-source or fail loudly. | ~1h | Would have caught the one malformed row this run at write time instead of at QA. Closes the last LLM-owned assembly gap (Class B). |
| R3 | **Kill the second prep CLI** — one entry point, `--engine playwright|requests|auto`, one `fetch_one`. | ~half day | Ends Class A structurally instead of guarding it. The divergence guard test stays as the backstop. |

### Tier 2 — high value, medium cost (recommended when convenient; ~1-2 days)

| # | Change | Cost | Why it pays |
|---|---|---|---|
| R4 | **One end-to-end pipeline test** in pytest: synthetic fixtures per ATS through `process_urls` → registry → normalize CSV → build XLSX, asserting the final artifacts (headers, cells, fills, capture sections). Network fully stubbed. | ~half day | The only thing that catches between-unit wiring bugs (Class C/D) before a live run does. Highest single protective value on this list. |
| R5 | **Company-brand canon for ATS-hosted tokens**: prefer the JD body's own signature ("About X" / footer / JSON-LD in embedded pages) for brand casing; tiny alias file as last resort. | ~2-3h | Cosmetic but visible on every artifact a recruiter-facing document is built from. Two live instances today. |

### Tier 3 — explicitly NOT recommended now (poor ROI)

- **Replacing the bespoke HTML converter with a library**: it is now heavily pinned by fixtures
  that encode hard-won real-world shapes; a library swap re-rolls all of that risk for little
  gain. Revisit only if a new source's markup defeats it.
- **Big-bang refactor of module boundaries**: the single-home pattern (`norm_contracts` for
  contracts, choke-point enrichment in prep) is working — the architecture is not the problem.
- **Chasing LinkedIn posted dates** beyond the current JSON-LD/`<time>` support: the guest
  fragment usually exposes only relative ages; honest `Unknown` is correct.
- **Spreadsheet styling refactor**: stable, contract-tested, user-approved.

### Process changes (free, arguably the biggest lever)

1. **Contract-freeze before implementation.** The final format landed fastest when the complete
   spec was written, consumers were audited read-only, and one atomic migration followed. Make
   that the default for any output-format change; treat mid-implementation spec edits as a new
   frozen revision, not a live patch.
2. **Live-canary loop as one step.** After any extraction change: run the (new) `qa_captures.py`
   gate against one staged re-fetch before declaring done. This was the de-facto loop that
   worked; it should cost one command, not a hand-built harness.
3. **Loud-or-fail as a review checklist item**: any new write/merge/skip path must either
   succeed, or say what it did not do. Silent no-ops are the repo's most expensive bug shape.
4. **Artifact-level assertions in every new test**: pin the written cell/file, not the helper's
   return value.

## 4. QA pass results (2026-07-30, post-delivery)

Cross-artifact audit of the 55-job tracker (rows↔captures↔registry): one malformed row
(repaired from the scoring run's own journal — no invented values), one brand-casing defect in a
capture header + CSV cell (repaired), stale pre-migration vet-run outputs quarantined into a
labeled `_staging-artifacts/` folder. All validations re-run and green afterwards: 27-column
contract, 55/55 capture refs resolving, label domains clean, no blank posted dates, both
tailored rows intact. Known accepted blemishes: a handful of scorer-enriched company names in
the CSV that carry parenthetical context beyond the capture's canonical name (informative, kept)
and one ATS-hosted capture whose header carries a run-together board-token name (Tier-2 R5).
