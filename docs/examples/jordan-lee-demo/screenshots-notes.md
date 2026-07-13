# Screenshot capture notes (Jordan Lee demo)

> Synthetic **Jordan Lee** data only (AI Product Marketing / GTM). Capture is **human-in-the-loop**: Claude prepares the staged state + artifacts; you capture the app/Finder images. PNGs land in **`docs/screenshots/`** (committed; synthetic content only).

## Status

- ⏳ Every shot is a **manual capture by you** (Finder / Claude Code / Numbers·Excel·Sheets / markdown preview / browser). *(There is no auto-generated hero — the real spreadsheet screenshot is the hero.)*
- The synthetic runtime is **staged right now** and the demo artifacts are **committed**, so no per-shot staging is needed — just open the path listed and capture. (Do **not** clean up the runtime staging until screenshots are done.)
- 🆕 **V2.2 (tracker UX):** `rankings.xlsx` is now a **sortable tracker** — human-editable columns first (`… ? [You …]`), AI detail to the right; header frozen; cells wrapped/centered/top; an inline **Status dropdown** + auto-filter on the job rows; **Lane** (the job's own category, stoplight-colored) vs **Lane Fit**; an **Instructions** tab; and a **section-color legend block** below the jobs (merged A:J). The spreadsheet capture should show these.

## The spreadsheet shot

- **`ranking-xlsx.png`** — **you** open `docs/examples/jordan-lee-demo/expected-outputs/rankings.xlsx` in **Numbers / Excel / Google Sheets** and capture the **authentic tracker UI** — ideally with a **Status dropdown open** and the **section-color legend** (the block just below the jobs) visible. This is the real product artifact **and** doubles as the marketing/hero image (there is no separate auto-rendered hero). *(A separate `instructions-tab.png` of the Instructions sheet is a nice optional add.)*

## Product-artifact shots (you capture)

| Filename | Open this (exact path) | What should be visible | Crop / focus | Dest | Capture |
|---|---|---|---|---|---|
| `folder-tree.png` | repo root in Finder / VS Code | numbered `ENGINE__… / PRIVATE__… … docs` structure | top level, expanded one level | both | manual |
| `intake-folders.png` | `PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO/01-about-you/` + `PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO/02-where-you-want-to-go/` (Finder) | evidence vs direction; Jordan's files | the two subfolders + their files | both | manual |
| `intake-review.png` | `__READY_TO_REVIEW__PRIVATE_GITIGNORED/06-25-26 - Intake Review/` (open `START HERE.md`) | the review-before-save gate; 8 files | `START HERE` + the numbered 1–7 files | both | manual |
| `review-hub.png` | `__READY_TO_REVIEW__PRIVATE_GITIGNORED/` (Finder) | the batch **and** the intake-review folder together | the hub with both folder types | both | manual |
| `prep-report.png` | `docs/examples/jordan-lee-demo/expected-outputs/prep-report.md` (md preview) | 4 usable / 1 thin / 0 failed / 0 dupes | the summary block | README | manual |
| `ranking-xlsx.png` | `docs/examples/jordan-lee-demo/expected-outputs/rankings.xlsx` (Numbers/Excel/Sheets) | the tracker UI: a **Status dropdown** open, human columns + AI detail, **Lane**/Location/Comp stoplight colors, and the **section-color legend** below the jobs | the open dropdown + the 4 colored rows + the legend block | both | manual |
| `tailored-output.png` | `docs/examples/jordan-lee-demo/expected-outputs/tailored - Thornbury (strong fit).md` (preview) | a tailored draft + its structure | a tailored block + a "Questions" peek | both | manual |
| `archive-summary.png` | `docs/examples/jordan-lee-demo/expected-outputs/archive-summary.md` (preview) | the archived-application record | the summary | README | manual |

## Marketing / website shots

| Filename | Open this (exact path) | What should be visible | Crop / focus | Dest | Capture |
|---|---|---|---|---|---|
| `questions-section.png` | `docs/examples/jordan-lee-demo/expected-outputs/tailored - Lyceum AI (truth-firewall).md` | the truth-firewall: 6 honesty questions | just the "Questions for the candidate" section | website | manual |
| `local-first-layout.png` | repo root in Finder | local-first / privacy-safe folder layout | the numbered folders (everything on your machine) | website | manual |
| `reconcile-loop.png` *(optional)* | `docs/examples/jordan-lee-demo/expected-outputs/reconcile-report - Thornbury.md` | the learning loop | §3 Observed changes + §4 Inferred lessons (or §5 Questions) | website (optional) | manual |

## Out of scope for screenshots

- ❌ Real companies, real URLs, real people, real job-search data.
- ❌ Anything from the (later) real-URL smoke test.
- ❌ Old pre-V2 folder paths, old `TAILOR` shots, old sample companies (inspiration only; do not import).
- ❌ Faking a screenshot — if it isn't captured yet, leave it uncaptured; don't mock a product UI.
