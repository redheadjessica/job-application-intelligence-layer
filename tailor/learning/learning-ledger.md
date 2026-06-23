# Application Learning Ledger

Durable lessons from **completed, submitted** applications, produced by the reconcile workflow
(`reconcile-spec.md`). Append-only, keyed by application folder.

**This file is seeded empty.** It fills in over time as you reconcile real, submitted applications.

## What this is

The long-term memory of the learning loop. Every entry records what the tailoring agent *recommended*
for a given application versus what you *actually submitted*, plus any lessons inferred from the
difference. It is the record layer — nothing here automatically edits a canonical generation file
(see `reconcile-spec.md` §8). Concrete edit proposals live in `source-update-queue.md`.

## How entries get added (never by hand from a draft)

1. You submit an application and move its folder into your trusted submitted-applications archive
   (`{{your submitted-applications archive}}`).
2. You run the reconcile workflow on that folder (see `reconcile-spec.md`). It compares the agent's
   first-pass recommendation against the final submitted résumé.
3. Reconcile **appends a candidate entry here**, keyed by the application folder name (so re-running is
   idempotent — the same folder is never double-appended), marked `pending`.
4. After you answer the "why did you change X?" questions, a confirm pass promotes confirmed lessons to
   `confirmed`.

**Hard rules:**
- An entry is **never** written from an in-progress tailoring draft — only from a reconcile of a
  submitted application in the archive.
- This file is human-reviewed; nothing here auto-edits canonical files.
- It stores lessons and patterns only — **never** raw personal cover-letter or application-answer text.
- This is a maintenance/learning file. It is **not** read during a normal résumé-generation run.

## Patterns tracker (recurring lessons across applications)

A roll-up of lessons that recur across applications. When the same lesson shows up in a second
application, increment its occurrence count and add the application here rather than creating a new row.

| Lesson (short) | Category | Occurrences | Applications | Status |
|---|---|---|---|---|
| _(none yet)_ | | | | |

Categories: routing · missed-evidence · claim-boundary · voice · skills · content/process.

## Entries

_(none yet — the first entry will be appended here by the first reconcile run.)_

Entry shape (one per completed application, keyed by folder name):

```
### <Company> — <Role> (<MM-DD-YY>)  ·  status: confirmed | pending
- Base recommended → used: <X> → <Y> (agreed / overrode)
- Accepted: <…>   Rejected: <…>   Manually added: <…>
- Evidence/story the agent missed: <…>
- Style corrections you made: <…>
- Claims softened/corrected: <…>
- Confirmed lesson(s): <…>
- Source files possibly affected: <profile / resume index / experience bank / summary / skills / reconciliation>
- Reconcile report: <path to that folder's reconcile-report - <Company> - <Role> - <run-date>.md>
```
