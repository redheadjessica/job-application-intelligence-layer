# JAIL Changelog

Project changelog. Reverse chronological. Maintained as readable project memory: what
changed, what was explored, and why it mattered — not a commit log. Git history already
holds the granular record; this file is the curated account.

Add rough entries here during normal work (see `scripts/README.md` for the format).
Run `python3 scripts/doc_synthesis.py` to consolidate them into readable threads.


<!-- changelog-processed-through: bd576955caf6495566fc88fcf9b7b5aadb8d10c8 -->
---

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
