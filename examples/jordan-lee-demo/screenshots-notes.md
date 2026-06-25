# Screenshot capture notes (Jordan Lee demo)

> Synthetic Jordan Lee data only. Capture is **human-in-the-loop**: Claude stages the state + prepares artifacts; you capture the actual images. **Finalized in V2.1 Unit 5** — this is the working checklist.

PNGs land in **`docs/screenshots/`** (committed; synthetic content only). Keep filenames aligned with the `[shot: …]` labels used by the README and `docs/jail-public-page-copy.md`.

## How to use this

For each shot: stage the needed synthetic state (see [`staging/README.md`](staging/README.md)), open the listed window / file, frame the suggested crop, capture, save the PNG to `docs/screenshots/<filename>.png`, then clean up staged runtime folders.

## Product-artifact shots (show the real product shape)

| Filename | Stage this state | Open / window | Shot shows | Crop / focus | README / site |
|---|---|---|---|---|---|
| `folder-tree.png` | clean checkout (no staging needed) | Finder or VS Code tree | numbered `00-INTAKE … docs` structure | top-level tree, expanded one level | both |
| `intake-folders.png` | Jordan resume + brag in `01-about-you/`, target JD in `02-where-you-want-to-go/` | Finder | evidence vs direction split | the two `00-INTAKE` subfolders + files | both |
| `intake-review.png` | run `/intake` on synthetic fixtures | the `… - Intake Review/` folder + `START HERE.md` | the review-before-save gate | START HERE + the numbered 1–7 files | both |
| `review-hub.png` | a staged batch + an intake-review folder present | `__READY TO REVIEW/` | where everything to review lives | the hub with both folder types | both |
| `prep-report.png` | staged batch with a prep-report sample | `0 - Prep Report/prep-report.md` | usable vs thin / failed / dupes | the summary section | README |
| `ranking-xlsx.png` | render `rankings.xlsx` | the `.xlsx` in Excel / Numbers / Sheets | the colored ranking spreadsheet | Comp / Location / Lane Fit + final_score colors | both (hero) |
| `tailored-output.png` | one tailored markdown present | the `application_resume_output … .md` | draft + "Questions for the candidate" | the Questions section + a tailored block | both |
| `archive-summary.png` | run `/archive` on a synthetic submitted folder | `archive-summary.md` | the archived record | the summary | README |

## Marketing / website shots (prettier, cropped)

| Filename | Stage this state | Open / window | Shot shows | Crop / focus | README / site |
|---|---|---|---|---|---|
| `hero-ranking.png` | rendered `rankings.xlsx` | spreadsheet app | clean ranking hero | tight crop, a few high-contrast rows | site (+ README hero) |
| `questions-section.png` | tailored markdown | editor / preview | honesty: "Questions for the candidate" | just that section | site |
| `truth-boundary.png` | intake review or boundary-rules artifact | the boundary-rules file | truth / privacy / local-first story | one boundary-rule example | site |
| `local-first-layout.png` | clean checkout | Finder tree | local-first workflow / folder layout | numbered folders | site |

## Out of scope for screenshots

- ❌ Real companies, real URLs, real people, real job-search data.
- ❌ Anything from the real-URL smoke test.
- ❌ Old pre-V2 folder paths, old `TAILOR` shots, old sample companies (inspiration only; do not import).
