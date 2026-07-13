# Screenshots plan (synthetic data only)

Real screenshots are a manual follow-up — capturing them needs a live Claude Code session. This file is the checklist + the synthetic data to use, so no real job-search materials ever appear in a shot.

## Hard rule: synthetic data only
Use the fictional persona **Jordan Lee — AI Product Marketing / GTM Strategy** for every screenshot and example. **Never** use a real resume, real job application, real submitted folder, real ranking, real company names from an actual search, or anything from a real job hunt.

## Synthetic persona & materials to stage

The full synthetic kit lives in **`docs/examples/jordan-lee-demo/`** (committed, 100% fictional). To capture in-context shots, stage those committed fixtures into the real (gitignored) runtime folders, then clean up — see `docs/examples/jordan-lee-demo/staging/README.md`.

- **Persona:** "Jordan Lee," a Senior Product Marketing Manager (B2B SaaS / workflow-tooling). Targeting AI Product Marketing, GTM Strategy, and Lifecycle/Growth roles at AI / tooling companies. Lanes: AI Product Marketing; GTM Strategy; Lifecycle/Growth.
- **`PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO/01-about-you/`:** a fictional PMM resume (launches, positioning, customer research, sales enablement, adoption programs; used AI tools to accelerate research/messaging/enablement) and a brag-doc line or two — fictional and internally consistent.
- **`PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO/02-where-you-want-to-go/`:** a fictional target JD (e.g. "Senior Product Marketing Manager, AI Workflows" at a fictional company).
- **`PRIVATE__YOUR_FILES_GITIGNORED/01-INBOX__YOUR_PRIVATE_INFO/paste-job-urls-to-rank-here.txt`:** `https://example.com/jobs/...` placeholder links only.
- **`jail.config.json`:** fictional comp / location / lane preferences (example copy committed under `docs/examples/jordan-lee-demo/fixtures/`).

## Shot list
| # | Screenshot | What it should show | Placeholder label |
|---|---|---|---|
| 1 | GitHub "Code → Download ZIP" | how to get the repo | `[shot: download-zip]` |
| 2 | Open folder in Claude Code (Local) | pointing Claude at the folder | `[shot: open-folder]` |
| 3 | Folder tree (`ENGINE__PUBLIC_GIT_TRACKED`, `PRIVATE__YOUR_FILES_GITIGNORED` … `docs`) | the numbered structure | `[shot: folder-tree]` |
| 4 | The two `PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO` folders | evidence vs. direction | `[shot: intake-folders]` |
| 5 | `/intake` staged review (`… - Intake Review/`) | the review-before-save gate | `[shot: intake-review]` |
| 6 | `__READY_TO_REVIEW__PRIVATE_GITIGNORED/` hub | where everything to review lives | `[shot: review-hub]` |
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

**V2.1 conventions:**
- Captured PNGs are committed under **`docs/screenshots/`** (visible content must be synthetic Jordan Lee data only).
- The rendered ranking **`.xlsx`** is an approved committed demo artifact (`docs/examples/jordan-lee-demo/expected-outputs/`) — reviewers can open it.
- Real-URL fetch smoke tests are **separate and disposable**: never committed, never screenshotted (see `docs/testing-and-caveats.md`).
