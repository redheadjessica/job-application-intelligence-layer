# Reconcile Spec

This defines the **post-application reconcile workflow**: how the system learns from a *completed, submitted* application without overfitting to one-off edits, misreading formatting noise, or turning the canonical source files into sludge.

**Core principle:** the active batch folder (`__READY TO REVIEW/<date>/`) is a **workspace** and is **never** a learning source. Your **submitted-applications archive** (`{{your submitted-applications archive}}`) is the **trusted archive**. Learning happens **only** from the archive, **only after submission**, and **only** through this reconcile pass.

**Status:** implemented by `.claude/workflows/reconcile.js` (Discover → Reconcile (parallel) → Synthesize). Invoke with `{folders:[...]}` for an explicit set, or `{archive, limit}` to scan; **`{archive}` is optional** — without it, reconcile reads `archive.path` from `jail.config.json` (fallback `05-SUBMITTED-APPLICATIONS`) and scans its year subfolders. (Move completed folders into the archive first with the **`/archive`** skill — reconcile only *reads* the archive, it never moves anything.) The workflow writes per-folder reports and appends to the **append-only learning instances** — `learning-ledger.md`, `source-update-queue.md`, `05a-summary-library.md`, and `06a-skills-library.md` (each created from its template if missing) — and **never** edits the primary generation files (`01`–`06`, resume index, experience bank); changes to those are only *proposals* in the queue, gated on human review (§8, §9).

**Cadence (manual, never automatic):** run reconcile after your first few applications, after a meaningfully changed final resume, when a new resume base emerges, or after repeated summary/skills corrections — less often once things stabilize. The discover step also warns when completed-looking folders are still sitting in `__READY TO REVIEW` (move them with `/archive`).

The ledger and queue are **maintenance/learning files. They are NOT in the tailoring parallel-read batch and are never read during a normal résumé-generation run.**

---

## 1. The manual reconcile workflow (v1)

Input: the path to **one** completed application folder in your archive, e.g. `{{your submitted-applications archive}}/<Company> - <Role> - <date>`.

It:
1. Runs the **readiness checks** (§5). If not ready, stops and reports why — writes nothing durable.
2. Reads the inputs: the scraped job post `.txt`, the original `application_resume_output - … .md`, the **final submitted résumé PDF**, and any cover-letter / application-answer files if present.
3. Compares **what the agent recommended** vs **what was actually submitted**, separating **observed changes** (fact, §6) from **inferred lessons** (hypotheses, §6).
4. Writes a **reconcile report** into that archive folder (§2 naming convention). The presence of any `reconcile-report - … .md` file in the folder is the "already reconciled" marker.
5. Appends **candidate** entries to the repo-side **ledger** (`learning-ledger.md`, keyed by folder) and any **proposed** items to the **queue** (`source-update-queue.md`), both marked pending per §7/§9.
6. Surfaces the **Questions for the user** for the ambiguous "why" items.
7. (v1.5 confirm step) After the user answers, a short pass promotes confirmed lessons in the ledger and updates queue item statuses. Applying a queue item to a canonical file is always a **separate human action**.

Reconcile **never** edits canonical files (§8) and **never** auto-applies queue items (§9).

---

## 2. The reconcile report (per-folder, lives in the archive folder)

One report per completed application, written beside the application it describes. Keep it tight — signal, not a full diff dump.

**Filename convention:** `reconcile-report - <Company> - <Role> - <run-date MM-DD-YY>.md`, where the Company/Role match the application and the **run date is the date the reconcile ran** (not the submission date — the folder already carries that). If a folder is re-reconciled later, the new run gets its own dated filename (the older report stays for history).

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
(Ignore pure formatting / whitespace / line-break artifacts from the source file → PDF conversion — semantic content only.)

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

## 3. `PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/learning/learning-ledger.md` (global, in the repo)

The durable, append-only record of lessons from completed applications. **Keyed by application folder name** so re-runs are idempotent (never double-append the same folder).

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

## 4. `PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/learning/source-update-queue.md` (global, in the repo)

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

When the same proposal recurs, **increment its occurrence count and add the application** to the existing item — do not add a duplicate item.

---

## 5. Readiness checks (can this folder be reconciled?)

A folder is **ready** only if all of these hold; otherwise reconcile stops, writes no durable artifact, and reports what's missing:
- It is under the **trusted archive** (`{{your submitted-applications archive}}`), not the active `__READY TO REVIEW/` workspace.
- It contains the **original `application_resume_output - … .md`** (the agent's first-pass recommendation).
- It contains the **final submitted résumé PDF** (ground truth) — a `*Resume*.pdf`, or the single non-JD `.pdf` in the folder (if multiple PDFs are ambiguous, discover flags it). The editable source file (`.pages`/`.docx`/etc.) without an exported/submitted PDF is **not** sufficient.
- It contains the **scraped job post `.txt`**.
- Cover letter / application-answer files are **optional** (used if present).
- It does **not** already contain a reconcile report (any `reconcile-report - … .md` file) — else it's already done, skip.

If the final PDF or the original output `.md` is missing, treat as **not ready** — do not guess.

---

## 6. Observed changes vs inferred lessons (the firewall)

- **Observed = fact.** Anything directly visible by comparing the proposal and the final PDF (a bullet present in one and not the other; a changed word; a different base). Stated plainly, no speculation. **Ignore pure formatting noise** (whitespace, line breaks, font/layout artifacts of the source file → PDF conversion) — compare *semantic content* only.
- **Inferred = hypothesis.** Any statement about **intent or why** or any generalizable **lesson**. Always labeled as inference, always carries a **confidence** level, and **never** stated as fact.
- The two never mix. Observations live in report §3; inferences in §4. This firewall is what prevents the system from "learning" a confident lesson from an ambiguous edit.

---

## 7. Classification rules (what something becomes)

Everything starts as an **observation**. It escalates only as evidence warrants:

- **Observation only** — a change whose meaning is clear but not generalizable, or any change by default. Recorded in report §3. No further action.
- **Question for the user** — the *why* is ambiguous and the answer would change whether it's a lesson (e.g. "you cut the contract-wins bullet — space, or not relevant here?"). Recorded in report §5.
- **Candidate ledger entry** — an observation plus a plausible lesson, logged for the record. Low bar (the ledger is memory). Marked `pending` until any gating question is answered.
- **Proposed source-file update** — the **high bar**. Allowed only when **both**: (a) it implies a **specific, concrete edit to a named canonical file**, and (b) it is **either confirmed by the user or recurs across ≥2 completed applications** (§9). One-offs never reach the queue unconfirmed.

---

## 8. Canonical files are never edited during reconcile (hard rule)

Reconcile's writes are: the per-folder reconcile report (`reconcile-report - … .md` in the archive folder) and appends to the **append-only learning instances** — `learning-ledger.md`, `source-update-queue.md`, `05a-summary-library.md`, `06a-skills-library.md` (created from templates if missing). It must **never** edit the **primary generation files**: `01-profile.md`, `02-resume-index.md`, `03-approved-truths-and-boundary-rules.md`, `04-experience-bank.md`, `05-summary-quick.md`, `06-skills-quick.md`. Changes to those are only *proposals* in the source-update queue, gated on human review. No exceptions, automated or not.

---

## 9. Canonical updates require confirmation OR recurrence

A proposed source-file update may graduate from "proposed" to **ready-to-apply** only when **at least one** of these is true:
- **The user explicitly confirms it**, or
- **It recurs across ≥2 completed applications** (the patterns tracker in the ledger shows occurrences ≥2).

Even when ready, the actual edit to a canonical file is **always a separate, deliberate human action** — the threshold promotes an item to "review me," it never auto-applies. This is the main guard against overfitting to a single ambiguous edit.

---

## 9a. Single occurrence is NOT moot (preservation + base/template candidates)

The ≥2-occurrence threshold governs **only** the auto-promotion of *unconfirmed rule edits*. It does **not** mean a single-occurrence insight is discarded. Two things must always hold:

- **Nothing is ever dropped as "moot."** Every observation, single-occurrence lesson, and watch-list item is preserved durably and stays retrievable (the queue watch list + the per-folder reports + the ledger). "Hasn't recurred yet" ≠ "not valuable." A one-off can be the most valuable thing in a batch.
- **One occurrence + the user's confirmation is enough.** The "confirm" branch of §9 means any single-occurrence item the user decides is real can be promoted now — it does not have to wait for a second occurrence. The recurrence branch only exists to *auto-surface* patterns not yet looked at.

**Reusable base / template candidates (copy-don't-rebuild).** A finalized, submitted résumé is itself a reusable artifact, not just a source of rule-lessons. When a reconcile produces a résumé that cleanly represents a role archetype (e.g. healthcare + mobile + retention), flag it as a **base / template candidate**: name the archetype and recommend that future similar roles **copy that exact résumé rather than rebuild it**. On the user's confirmation, it is registered as a canonical base in the resume index — **from a single occurrence**. The ≥2 gate never applies to base/template promotion; that path is confirmation-only. Reconcile records the candidate and surfaces it for review; it never edits the registry itself.

---

## 10. Minimal v1 flow (manual, one folder)

1. The user points reconcile at one archive folder.
2. Readiness check (§5). If not ready → stop, report what's missing, write nothing durable.
3. Read the four inputs.
4. Write the reconcile report (`reconcile-report - <Company> - <Role> - <run-date>.md`, §2) into that folder: observed (fact) · inferred (hypotheses + confidence) · Questions for the user · candidate ledger entries · proposed queue items (gated). Status = `pending-your-answers`.
5. Append candidate entries to the ledger (keyed by folder, marked pending) and any proposed items to the queue (marked `needs-your-confirmation` or `needs-2nd-occurrence`).
6. Surface the Questions for the user.
7. **Confirm step (v1.5):** after the user answers, promote confirmed lessons in the ledger, update queue statuses, and flip the report to `confirmed`. Canonical files remain untouched.

---

## 11. Later v2 flow (scan the archive)

1. Scan the archive for application folders that **lack any reconcile report** (no `reconcile-report - … .md` file).
2. For each, run the readiness check (§5); **skip + flag** anything incomplete (don't reconcile a half-finished folder).
3. Run the v1 reconcile on each ready folder.
4. Post a summary: reconciled N, skipped M (with reasons), new questions, new/updated queue items.
5. Still **human-gated** for any canonical change; still **pattern-thresholded** (§9).
6. Idempotency: the reconcile-report marker (`reconcile-report - … .md`) + folder-keyed ledger entries mean re-running the scan never double-processes a folder. Can run on-command first, then nightly (launchd) later.

---

## Anti-sludge guardrails (summary)

- **Learn from patterns, not one-offs** — single edits never propose canonical changes (§7, §9).
- **Observed/inferred firewall** — facts and hypotheses never mix; every inference carries confidence (§6).
- **Formatting noise is ignored** — semantic content only (§6).
- **Two human gates** — answer the *why* questions, then approve the canonical edit (§7, §9, §10).
- **Idempotent + keyed** — marker file + folder-keyed entries; recurring proposals merge and increment, not duplicate (§3, §4, §11).
- **Confidentiality** — ledger/queue store lessons and patterns, never raw personal cover-letter or application-answer text.

---

## 9b. Submission = seal of approval (revised promotion flow)

**Once the candidate has actually applied with a resume, that is their seal of approval — it's good to use for other jobs.** No separate confirmation step.

What this changes:
- **Base registration is automatic.** Reconcile's synthesis step edits `PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/02-resume-index.md` directly (named anchor for a new/materially-different archetype; "newest exemplar" line for a re-skin). Additive only, logged in the run output, reversible via git. The queue's "Base / template candidates" section is retired for new items.
- **Finalized summaries flow into `05a-summary-library.md` automatically** (verbatim, labeled by archetype + company + date).
- **The human gate moves, it doesn't disappear:** it now sits exactly on the observed/inferred line. The candidate's verbatim submitted words and files auto-promote; INFERRED generalizations ("they seem to prefer…", proposed rule changes, voice-spec edits) still require confirmation via the queue. The candidate approves rules, not their own words.
- The §8 "never edit canonical files" rule gains exactly two carve-outs: 02-resume-index registry additions and 05a verbatim-summary appends. Nothing else.

---

## 12. Cover-letter reconcile (addendum — requires the optional cover-letter module)

Cover letters produced by the `cover-letter` workflow get their own reconcile lane inside the same pass, with the same church-and-state discipline. Skip this lane entirely if the candidate hasn't set up `04-TAILOR/cover-letter/` (no feedback-queue instance).

**The baseline vs ground-truth rule:**
- The candidate **never edits the generated `.docx`** — it is always, verbatim, the agent's final output. The equivalent markdown baseline is `_cl_work/final.md` in the job folder.
- The **submitted version is always a PDF**. The delta between the baseline and the submitted PDF **is** the candidate's feedback, and it is the only thing this lane learns from.
- Do NOT treat the agent-generated `.docx`, `_cl_work/` drafts, or the review packet as "what was submitted." They are the recommendation side of the diff, never the truth side.

**Finding the submitted cover letter (real-world shapes, all must be handled):**
1. A combined PDF named like a resume where the **last page(s) are actually the cover letter** (most common: 2-page resume + page 3 = letter).
2. Separate resume PDF and cover-letter PDF.
3. Both a combined PDF **and** separate extracts — prefer the separate cover-letter PDF, and note if the combined copy differs.
4. Application-question answers, in the PDF or as **screenshots** in the folder — these feed the answers lane (§13); flag them rather than ignore them.

Detect cover-letter content by **content heuristics, not filenames**: a salutation ("Dear … team,"), a `Re:` line, a sign-off ("Looking forward…", "Warmly,"), letter-length prose. Filenames lie (e.g. a file named `…Resume….pdf` whose page 3 is the letter).

**Comparison (same observed/inferred firewall as §6):**
- Observed: sentences added/removed/reworded, links added/removed/re-anchored, tone shifts, length changes, structural changes (bullets ↔ paragraphs).
- Ignore formatting noise (hyphenation, line breaks, smart-quote differences, PDF extraction artifacts).
- Every candidate lesson is framed in plain English: **"You did Y on the [Company] letter — was that on purpose? Should it become the default?"** with before/after text.

**Where lessons go (NOT the resume learning files):**
- Candidates append to **`04-TAILOR/cover-letter/feedback-queue.md`** (pending, folder-keyed, idempotent).
- After the candidate confirms, entries are promoted to **`04-TAILOR/cover-letter/feedback-ledger.md`** — the only cover-letter learning file read at generation time.
- Voice-rule changes that contradict the voice spec are queue items proposing a spec edit — applying them to the spec is always a separate human-approved action, exactly like §9's canonical-file gate.

The per-folder reconcile report gains a `## Cover letter` section when a letter was found (or a one-line "no cover letter in folder" note). Pattern thresholds (§9) apply: one-off edits inform, repeated edits (2+) propose.

---

## 13. Token-efficient extraction, anecdote harvest, and the answers lane

**Principle: pay LLM tokens for interpretation, never for finding or re-reading.** Almost all reconcile cost is reading; most of what's read never changes. So:

**Extraction-first (deterministic, cached forever).** Every per-folder reconcile begins by running `ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/learning/extract_submission.py "<folder>"`. It writes `_extracted/`: `submitted-resume.txt`, `submitted-coverletter.txt` (pages found by content — handles the letter-as-page-3 shape), `submitted-answers.txt` (a pasted `application-answers.txt` always wins over PDF pages), `coverletter-diff.txt` (sentence-level unified diff vs `_cl_work/final.md`, normalized for PDF artifacts: ligatures, bullets, letterhead chrome — the candidate's signature/domains come from the cover-letter `config.json`), and `MANIFEST.txt`. Agents read these instead of PDFs; the diff IS the cover-letter feedback signal. Screenshots are transcribed by an agent at most ONCE (appended to `submitted-answers.txt`, marked with the source filename) and never re-read. Extraction is cached — re-running reconcile on a folder costs ~0 reading tokens. Capture tip for the candidate: paste answer text into `application-answers.txt` when convenient, screenshots when not.

**Anecdote harvest → `04-TAILOR/cover-letter/anecdote-bank.md` (direct entry, tagged).** Personal stories and lived details found in submitted letters/answers — especially ones the candidate added by hand (visible in the diff) — are their own words: observed facts, not inferences. They enter the bank directly, tagged with their source application (no queue gate; the queue remains for style/rule inferences). The bank tracks `Used in` per story so the writer never repeats a story to the same company. The bank is a generation-time canon file (writer + evaluator read it); reconcile appends entries and usage lines but never rewrites existing story text.

**Answers lane (harvest-only) → `PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/learning/answer-bank.md`.** No baseline exists for application answers (nothing drafts them yet), so there is nothing to diff — reconcile harvests question+answer pairs keyed by archetype (why-this-company, how-you-use-AI, …), condensing long answers to argument + anecdote slugs. This bank seeds future answer drafting; if an answer-drafting lane is built later, it gains a baseline and joins the diff-based learning like cover letters.

**Model discipline:** discovery on a small/fast model; one mid-tier agent per folder (reads extracts + diff, not PDFs); one mid-tier synthesis writer. Screenshots read once, in the folder agent, only when the manifest says their content is missing.
