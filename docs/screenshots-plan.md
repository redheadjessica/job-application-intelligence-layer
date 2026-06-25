# Screenshots plan (synthetic data only)

Real screenshots are a manual follow-up — capturing them needs a live Claude Code session. This file is the checklist + the synthetic data to use, so no real job-search materials ever appear in a shot.

## Hard rule: synthetic data only
Use the fictional persona **Jordan Lee — strategic finance** for every screenshot and example. **Never** use a real resume, real job application, real submitted folder, real ranking, real company names from an actual search, or anything from a real job hunt.

## Synthetic persona & materials to stage
- **Persona:** "Jordan Lee," a strategic-finance / FP&A leader (~10 yrs). Lanes: Strategic Finance / FP&A leadership; BizOps.
- **`00-INTAKE/01-about-you/`:** a one-page fake resume (e.g. Northwind — Sr FP&A Manager; Acme — Financial Analyst) and a brag-doc line or two.
- **`00-INTAKE/02-where-you-want-to-go/`:** a fake target JD (e.g. "Director of FP&A, Meridian — Series C fintech").
- **`01-INBOX/paste-job-urls-to-rank-here.txt`:** 3–4 obviously-fake links (`https://example.com/jobs/…`) or a note that they're placeholders.
- **`jail.config.json`:** fake comp (target 220 / floor 180), home metro "NYC", arrangement ratings, two lanes.

## Shot list
| # | Screenshot | What it should show | Placeholder label |
|---|---|---|---|
| 1 | GitHub "Code → Download ZIP" | how to get the repo | `[shot: download-zip]` |
| 2 | Open folder in Claude Code (Local) | pointing Claude at the folder | `[shot: open-folder]` |
| 3 | Folder tree (`00-INTAKE` … `docs`) | the numbered structure | `[shot: folder-tree]` |
| 4 | The two `00-INTAKE` folders | evidence vs. direction | `[shot: intake-folders]` |
| 5 | `/intake` staged review (`… - Intake Review/`) | the review-before-save gate | `[shot: intake-review]` |
| 6 | `__READY TO REVIEW/` hub | where everything to review lives | `[shot: review-hub]` |
| 7 | Prep report (`0 - Prep Report/prep-report.md`) | usable vs. thin/failed/dupes | `[shot: prep-report]` |
| 8 | Ranking spreadsheet (Jordan's batch) | Comp/Location/Lane Fit + colors | `[shot: ranking-xlsx]` |
| 9 | Tailored output (`application_resume_output - … .md`) | the draft + Questions section | `[shot: tailored-output]` |
| 10 | `/archive` summary (`archive-summary.md`) | the archived record | `[shot: archive-summary]` |

## What must NOT appear in any screenshot
- Real names, employers, or roles from an actual search — Jordan Lee only.
- Real comp numbers, real rankings, real submitted resumes/PDFs.
- The author's private files, a real `jail.config.json`, or any gitignored instance with real data.
- API keys, account details, or anything in `.claude/settings.local.json`.

## Where these are used
The README's `<!-- TODO: screenshot -->` markers and `docs/jail-public-page-copy.md`'s screenshot placeholders reference these labels.
