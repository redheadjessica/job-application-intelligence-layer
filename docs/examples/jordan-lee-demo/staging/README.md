# staging/ — fixtures → runtime → screenshots → cleanup

> 100% fictional demo data only. See [`../README.md`](../README.md) for the full safety rules.

The committed fixtures in [`../fixtures/`](../fixtures/) are the **durable source**. To run the workflow or capture in-context screenshots, you **copy** them into the real (gitignored) runtime folders, do the work, capture, then **clean up**. The committed originals never move.

## The loop

1. **Copy** synthetic fixtures into runtime locations (table below).
2. **Run / open** the relevant step (intake review, prep, ranking, tailor, archive, reconcile).
3. **Capture** screenshots (see [`../screenshots-notes.md`](../screenshots-notes.md)).
4. **Clean up** the staged runtime folders.

## Which runtime folders may be temporarily populated

All of these are **already gitignored**, so staging into them will not accidentally commit runtime data:

| Runtime path | Holds (synthetic) | Ignored by |
|---|---|---|
| `PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO/01-about-you/` | Jordan's resume + brag doc | `PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO/01-about-you/*` |
| `PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO/02-where-you-want-to-go/` | target JD | `PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO/02-where-you-want-to-go/*` |
| `jail.config.json` | Jordan's preferences | `jail.config.json` |
| `__READY TO REVIEW/<batch>/` | prep report, rankings, tailored, source material | `__READY TO REVIEW/*/` |
| `__READY TO REVIEW/<date> - Intake Review/` | staged intake review | `__READY TO REVIEW/*/` |
| `05-SUBMITTED-APPLICATIONS/<year>/` | archived application | `05-SUBMITTED-APPLICATIONS/*` |
| `PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/*.md`, `04-TAILOR/0X-*.md` | instance source-of-truth files | 03-VETTING: wholesale (PRIVATE root); 04-TAILOR: per-file (until migrated) |

### The inbox working copy

`PRIVATE__YOUR_FILES_GITIGNORED/01-INBOX__YOUR_PRIVATE_INFO/paste-job-urls-to-rank-here.txt` is a **gitignored working copy** (created from the tracked template in `ENGINE__PUBLIC_GIT_TRACKED/01-INBOX/` by `new_batch.py`). Placeholder URLs staged into it for a screenshot never show in `git status`; just delete them during cleanup. Do not edit the tracked `.template.txt` itself.

## How to avoid accidentally committing runtime / private data

- **Never `git add -f`** a runtime / private path to "save the demo." Commit demo data in `examples/` instead.
- After staging, run `git status` — staged runtime folders should be **absent** (ignored). If any appear, stop and recheck `.gitignore`.
- Only **synthetic Jordan Lee** content ever goes into these folders. If real data is present, do not capture or commit.

## Screenshots of runtime folders

Allowed — **only** when the folder is populated with synthetic Jordan Lee data. The resulting PNG (synthetic content) may be committed under `docs/screenshots/`. The runtime folder itself stays gitignored and gets cleaned up.

## Note

Screenshot capture is a **shared / human-in-the-loop** process. Claude prepares the staged synthetic state and artifacts; the human captures Finder / Claude Code / GitHub / spreadsheet / browser shots. See [`../screenshots-notes.md`](../screenshots-notes.md).
