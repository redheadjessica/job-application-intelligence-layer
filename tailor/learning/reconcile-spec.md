# Reconcile Spec

This defines the **post-application reconcile workflow**: how the system learns from a *completed,
submitted* application without overfitting to one-off edits, misreading formatting noise, or turning
the canonical source files into sludge.

**Core principle:** the active batch folder (`__READY TO REVIEW/<date>/`) is a **workspace** and is
**never** a learning source. Your **submitted-applications archive** (`{{your submitted-applications
archive}}`) is the **trusted archive**. Learning happens **only** from the archive, **only after
submission**, and **only** through this reconcile pass.

**Status:** implemented by `.claude/workflows/reconcile.js` (Discover → Reconcile (parallel) →
Synthesize). Invoke with `{folders:[...]}` for an explicit set, or `{archive, limit}` to scan for
unreconciled folders. The `learning-ledger.md` ledger and `source-update-queue.md` queue live beside
this spec. The workflow writes per-folder reports + appends to the ledger / queue only; it never edits
canonical generation files, and finalized summaries are returned as a paste-ready block for human
review (not auto-written to the summary library). None of the canonical generation files, the resume
index, or the experience bank is ever touched by reconcile (see §8).

The ledger and queue are **maintenance/learning files. They are NOT in the tailoring parallel-read
batch and are never read during a normal résumé-generation run.**

---

## 1. The manual reconcile workflow (v1)

Input: the path to **one** completed application folder in your archive, e.g.
`{{your submitted-applications archive}}/<Company> - <Role> - <date>`.

It:
1. Runs the **readiness checks** (§5). If not ready, stops and reports why — writes nothing durable.
2. Reads the inputs: the scraped job post `.txt`, the original `application_resume_output - … .md`, the
   **final submitted résumé PDF**, and any cover-letter / application-answer files if present.
3. Compares **what the agent recommended** vs **what was actually submitted**, separating **observed
   changes** (fact, §6) from **inferred lessons** (hypotheses, §6).
4. Writes a **reconcile report** into that archive folder (§2 naming convention). The presence of any
   `reconcile-report - … .md` file in the folder is the "already reconciled" marker.
5. Appends **candidate** entries to the repo-side **ledger** (`learning-ledger.md`, keyed by folder) and
   any **proposed** items to the **queue** (`source-update-queue.md`), both marked pending per §7/§9.
6. Surfaces the **Questions for the user** for the ambiguous "why" items.
7. (v1.5 confirm step) After the user answers, a short pass promotes confirmed lessons in the ledger and
   updates queue item statuses. Applying a queue item to a canonical file is always a **separate human
   action**.

Reconcile **never** edits canonical files (§8) and **never** auto-applies queue items (§9).

---

## 2. The reconcile report (per-folder, lives in the archive folder)

One report per completed application, written beside the application it describes. Keep it tight —
signal, not a full diff dump.

**Filename convention:** `reconcile-report - <Company> - <Role> - <run-date MM-DD-YY>.md`, where the
Company/Role match the application and the **run date is the date the reconcile ran** (not the
submission date — the folder already carries that). If a folder is re-reconciled later, the new run gets
its own dated filename (the older report stays for history).

```
# Reconcile Report — <Company> — <Role>

- **Application folder:** <folder name>
- **Submitted (from folder date):** <MM-DD-YY>
- **Reconciled:** <YYYY-MM-DD>
- **Status:** pending-your-answers | confirmed
- **Inputs found:** scraped JD ✓ | original output .md ✓ | final PDF ✓ | cover letter ▢ | answers ▢

## 1. What the agent recommended
- Base recommended: <base> (runner-up: <base>)
- Summary direction, key page-1 bullets, skills lean, strategic/inferred items, content opportunity — brief.

## 2. What was actually submitted (from the final PDF — ground truth)
- Base/framing actually used (inferred from structure; label confidence)
- Summary used, key bullets, skills line, writing samples, cover letter present?

## 3. Observed changes (FACT — no speculation)
Categorized diffs, each a neutral observation:
- Base/framing: <agreed | overrode to X>
- Bullets: accepted / rejected / **added** (a bullet or story in the final that the agent did not propose)
- Summary: <changed how>
- Skills: <added / dropped>
- Claims: <softened / corrected> (e.g. a claim made more precise)
- Style: <em dash removed, verb swapped, "not just X but Y" rewritten, etc.>
- Writing samples: <swapped / reordered>
(Ignore pure formatting / whitespace / line-break artifacts from .pages→PDF — semantic content only.)

## 4. Inferred lessons (HYPOTHESES — labeled, never stated as fact)
For each: **category** (routing / missed-evidence / claim-boundary / voice / skills / content) ·
**confidence** (high / med / low) · the **why hypothesis** · what it *might* imply.

## 5. Questions for the user
The ambiguous "why did you change X?" items whose answer determines whether something is a real lesson.
Any proposed source-file update is gated on these (§7, §9).

## 6. Proposed ledger entries (candidate → learning-ledger.md)
What would be logged for the record, marked pending until §5 is answered.

## 7. Proposed source-update items (candidate → source-update-queue.md, gated)
Only specific, named-file proposals. Each marked: **needs your confirmation** or **needs a 2nd
occurrence** (§9). One-offs do not appear here.
```

---

## 3. `tailor/learning/learning-ledger.md` (global, in the repo)

The durable, append-only record of lessons from completed applications. **Keyed by application folder
name** so re-runs are idempotent (never double-append the same folder).

```
# Application Learning Ledger

Durable lessons from COMPLETED, SUBMITTED applications (via reconcile). Append-only. Keyed by folder.
Never written from a tailoring draft — only from an archive reconcile. Human-reviewed; not auto-applied.

## Patterns tracker (recurring lessons across applications)
| Lesson (short) | Category | Occurrences | Applications | Status |
|---|---|---|---|---|
| <short lesson> | claim-boundary | 2 | <App A>, <App B> | ready-for-queue |

## Entries

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

---

## 4. `tailor/learning/source-update-queue.md` (global, in the repo)

Proposed canonical edits awaiting human review. **Never auto-applied.**

```
# Source-Update Queue

Proposed edits to canonical files, awaiting human review.
HARD RULE: reconcile only PROPOSES here. A human applies edits, separately, after review (see §9).

## Queue
### [<status>] <target file> — <one-line change>
- **Proposed change:** <specific, concrete edit>
- **Rationale:** <why>
- **Evidence:** <applications supporting it> · **occurrences:** <N>
- **Status:** proposed | needs-2nd-occurrence | confirmed-ready-to-apply | applied | rejected
- **Source:** <reconcile-report path(s)>
```

When the same proposal recurs, **increment its occurrence count and add the application** to the
existing item — do not add a duplicate item.

---

## 5. Readiness checks (can this folder be reconciled?)

A folder is **ready** only if all of these hold; otherwise reconcile stops, writes no durable artifact,
and reports what's missing:
- It is under the **trusted archive** (`{{your submitted-applications archive}}`), not the active
  `__READY TO REVIEW/` workspace.
- It contains the **original `application_resume_output - … .md`** (the agent's first-pass recommendation).
- It contains the **final submitted résumé PDF** (ground truth). A `.pages` without an exported PDF is
  **not** sufficient.
- It contains the **scraped job post `.txt`**.
- Cover letter / application-answer files are **optional** (used if present).
- It does **not** already contain a reconcile report (any `reconcile-report - … .md` file) — else it's already done, skip.

If the final PDF or the original output `.md` is missing, treat as **not ready** — do not guess.

---

## 6. Observed changes vs inferred lessons (the firewall)

- **Observed = fact.** Anything directly visible by comparing the proposal and the final PDF (a bullet
  present in one and not the other; a changed word; a different base). Stated plainly, no speculation.
  **Ignore pure formatting noise** (whitespace, line breaks, font/layout artifacts of `.pages`→PDF) —
  compare *semantic content* only.
- **Inferred = hypothesis.** Any statement about **intent or why** or any generalizable **lesson**.
  Always labeled as inference, always carries a **confidence** level, and **never** stated as fact.
- The two never mix. Observations live in report §3; inferences in §4. This firewall is what prevents
  the system from "learning" a confident lesson from an ambiguous edit.

---

## 7. Classification rules (what something becomes)

Everything starts as an **observation**. It escalates only as evidence warrants:

- **Observation only** — a change whose meaning is clear but not generalizable, or any change by
  default. Recorded in report §3. No further action.
- **Question for the user** — the *why* is ambiguous and the answer would change whether it's a lesson
  (e.g. "you cut the contract-wins bullet — space, or not relevant here?"). Recorded in report §5.
- **Candidate ledger entry** — an observation plus a plausible lesson, logged for the record. Low bar
  (the ledger is memory). Marked `pending` until any gating question is answered.
- **Proposed source-file update** — the **high bar**. Allowed only when **both**: (a) it implies a
  **specific, concrete edit to a named canonical file**, and (b) it is **either confirmed by the user
  or recurs across ≥2 completed applications** (§9). One-offs never reach the queue unconfirmed.

---

## 8. Canonical files are never edited during reconcile (hard rule)

Reconcile's only writes are: the per-folder reconcile report (`reconcile-report - … .md` in the archive
folder) and appends to the ledger / queue (in the repo). It must **never** edit the canonical generation
files, the resume index, the experience bank, the summary/skills libraries, or any other
canonical/source file. No exceptions, automated or not.

---

## 9. Canonical updates require confirmation OR recurrence

A proposed source-file update may graduate from "proposed" to **ready-to-apply** only when **at least
one** of these is true:
- **The user explicitly confirms it**, or
- **It recurs across ≥2 completed applications** (the patterns tracker in the ledger shows occurrences ≥2).

Even when ready, the actual edit to a canonical file is **always a separate, deliberate human action** —
the threshold promotes an item to "review me," it never auto-applies. This is the main guard against
overfitting to a single ambiguous edit.

---

## 9a. Single occurrence is NOT moot (preservation + base/template candidates)

The ≥2-occurrence threshold governs **only** the auto-promotion of *unconfirmed rule edits*. It does
**not** mean a single-occurrence insight is discarded. Two things must always hold:

- **Nothing is ever dropped as "moot."** Every observation, single-occurrence lesson, and watch-list
  item is preserved durably and stays retrievable (the queue watch list + the per-folder reports + the
  ledger). "Hasn't recurred yet" ≠ "not valuable." A one-off can be the most valuable thing in a batch.
- **One occurrence + the user's confirmation is enough.** The "confirm" branch of §9 means any
  single-occurrence item the user decides is real can be promoted now — it does not have to wait for a
  second occurrence. The recurrence branch only exists to *auto-surface* patterns not yet looked at.

**Reusable base / template candidates (copy-don't-rebuild).** A finalized, submitted résumé is itself a
reusable artifact, not just a source of rule-lessons. When a reconcile produces a résumé that cleanly
represents a role archetype (e.g. healthcare + mobile + retention), flag it as a **base / template
candidate**: name the archetype and recommend that future similar roles **copy that exact résumé rather
than rebuild it**. On the user's confirmation, it is registered as a canonical base in the resume index
— **from a single occurrence**. The ≥2 gate never applies to base/template promotion; that path is
confirmation-only. Reconcile records the candidate and surfaces it for review; it never edits the
registry itself.

---

## 10. Minimal v1 flow (manual, one folder)

1. The user points reconcile at one archive folder.
2. Readiness check (§5). If not ready → stop, report what's missing, write nothing durable.
3. Read the four inputs.
4. Write the reconcile report (`reconcile-report - <Company> - <Role> - <run-date>.md`, §2) into that folder: observed (fact) · inferred (hypotheses + confidence) ·
   Questions for the user · candidate ledger entries · proposed queue items (gated). Status =
   `pending-your-answers`.
5. Append candidate entries to the ledger (keyed by folder, marked pending) and any proposed items to
   the queue (marked `needs-your-confirmation` or `needs-2nd-occurrence`).
6. Surface the Questions for the user.
7. **Confirm step (v1.5):** after the user answers, promote confirmed lessons in the ledger, update
   queue statuses, and flip the report to `confirmed`. Canonical files remain untouched.

---

## 11. Later v2 flow (scan the archive)

1. Scan the archive for application folders that **lack any reconcile report** (no `reconcile-report - … .md` file).
2. For each, run the readiness check (§5); **skip + flag** anything incomplete (don't reconcile a
   half-finished folder).
3. Run the v1 reconcile on each ready folder.
4. Post a summary: reconciled N, skipped M (with reasons), new questions, new/updated queue items.
5. Still **human-gated** for any canonical change; still **pattern-thresholded** (§9).
6. Idempotency: the reconcile-report marker (`reconcile-report - … .md`) + folder-keyed ledger entries mean re-running the scan
   never double-processes a folder. Can run on-command first, then nightly (launchd) later.

---

## Anti-sludge guardrails (summary)

- **Learn from patterns, not one-offs** — single edits never propose canonical changes (§7, §9).
- **Observed/inferred firewall** — facts and hypotheses never mix; every inference carries confidence (§6).
- **Formatting noise is ignored** — semantic content only (§6).
- **Two human gates** — answer the *why* questions, then approve the canonical edit (§7, §9, §10).
- **Idempotent + keyed** — marker file + folder-keyed entries; recurring proposals merge and increment,
  not duplicate (§3, §4, §11).
- **Confidentiality** — ledger/queue store lessons and patterns, never raw personal cover-letter or
  application-answer text.
