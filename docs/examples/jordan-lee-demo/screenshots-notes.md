# Screenshot capture notes (Jordan Lee demo)

> Synthetic **Jordan Lee** data only (AI Product Marketing / GTM). Capture is **human-in-the-loop**: Claude prepares the staged state + artifacts; you capture the app/Finder images. PNGs land in **`docs/screenshots/`** (committed; synthetic content only).

## Status (V2.1 Unit 5 — Phase A)

- ✅ **`hero-ranking.png` is auto-generated and committed** — a clean marketing table rendered from the committed `rankings.xlsx` (matplotlib). This is the **marketing hero**, *not* a replacement for the real spreadsheet UI.
- ⏳ Everything else is a **manual capture by you** (Finder / Claude Code / Numbers·Excel·Sheets / markdown preview / browser).
- The synthetic runtime is **staged right now** and the demo artifacts are **committed**, so no per-shot staging is needed — just open the path listed and capture. (Do **not** clean up the runtime staging until screenshots are done.)

## The two spreadsheet shots (do both)

1. **`hero-ranking.png`** — auto-generated (done). Marketing/website hero. Clean colored table; not the literal app.
2. **`ranking-xlsx.png`** — **you** open `docs/examples/jordan-lee-demo/expected-outputs/rankings.xlsx` in **Numbers / Excel / Google Sheets** and capture the **authentic spreadsheet UI**. This is the real product artifact.

## Product-artifact shots (you capture)

| Filename | Open this (exact path) | What should be visible | Crop / focus | Dest | Capture |
|---|---|---|---|---|---|
| `folder-tree.png` | repo root in Finder / VS Code | numbered `00-INTAKE … docs` structure | top level, expanded one level | both | manual |
| `intake-folders.png` | `00-INTAKE/01-about-you/` + `00-INTAKE/02-where-you-want-to-go/` (Finder) | evidence vs direction; Jordan's files | the two subfolders + their files | both | manual |
| `intake-review.png` | `__READY TO REVIEW/06-25-26 - Intake Review/` (open `START HERE.md`) | the review-before-save gate; 8 files | `START HERE` + the numbered 1–7 files | both | manual |
| `review-hub.png` | `__READY TO REVIEW/` (Finder) | the batch **and** the intake-review folder together | the hub with both folder types | both | manual |
| `prep-report.png` | `docs/examples/jordan-lee-demo/expected-outputs/prep-report.md` (md preview) | 4 usable / 1 thin / 0 failed / 0 dupes | the summary block | README | manual |
| `ranking-xlsx.png` | `docs/examples/jordan-lee-demo/expected-outputs/rankings.xlsx` (Numbers/Excel) | the colored ranking spreadsheet | Comp / Location / Lane Fit + `final_score` colors, all 4 rows | both | manual |
| `tailored-output.png` | `docs/examples/jordan-lee-demo/expected-outputs/tailored - Thornbury (strong fit).md` (preview) | a tailored draft + its structure | a tailored block + a "Questions" peek | both | manual |
| `archive-summary.png` | `docs/examples/jordan-lee-demo/expected-outputs/archive-summary.md` (preview) | the archived-application record | the summary | README | manual |

## Marketing / website shots

| Filename | Open this (exact path) | What should be visible | Crop / focus | Dest | Capture |
|---|---|---|---|---|---|
| `hero-ranking.png` | — (already rendered) | clean ranking hero, full contrast | the whole table + the quarantine note | website (+ README hero) | **auto ✅** |
| `questions-section.png` | `docs/examples/jordan-lee-demo/expected-outputs/tailored - Lyceum AI (truth-firewall).md` | the truth-firewall: 6 honesty questions | just the "Questions for the candidate" section | website | manual |
| `local-first-layout.png` | repo root in Finder | local-first / privacy-safe folder layout | the numbered folders (everything on your machine) | website | manual |
| `reconcile-loop.png` *(optional)* | `docs/examples/jordan-lee-demo/expected-outputs/reconcile-report - Thornbury.md` | the learning loop | §3 Observed changes + §4 Inferred lessons (or §5 Questions) | website (optional) | manual |

## Out of scope for screenshots

- ❌ Real companies, real URLs, real people, real job-search data.
- ❌ Anything from the (later) real-URL smoke test.
- ❌ Old pre-V2 folder paths, old `TAILOR` shots, old sample companies (inspiration only; do not import).
- ❌ Faking a screenshot — if it isn't captured yet, leave it uncaptured; don't mock a product UI.
