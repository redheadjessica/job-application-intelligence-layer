# Job Application Intelligence Layer (JAIL)

An open-source, run-it-locally pipeline that turns a messy job search into one chained flow: **fetch job posts you provide → vet a batch → tailor the top few → learn from what you submit.** The pipeline does not discover or search for jobs on its own — the user supplies the job URLs/posts.

Clone this repo, run **`/intake`** once to generate your own personal files from your resume, then run the pipeline on batches of job URLs **you provide**. Everything personal to you is a **generated instance file** (gitignored); the engine and the blank **`.template.md` / `.template.json`** files it fills are shared and stay generic.

> The full V2 end-to-end user journey is documented in **`docs/v2-end-to-end-workflow.md`** (source of truth for the workflow).

---

## Repo layout

Three visible top-level roots: **`ENGINE__PUBLIC_GIT_TRACKED/`** (public mechanism + templates, tracked), **`PRIVATE__YOUR_FILES_GITIGNORED/`** (the user's generated instances + materials + archive, gitignored), and **`__READY_TO_REVIEW__PRIVATE_GITIGNORED/`** (generated review output, gitignored). Inside ENGINE and PRIVATE the numbered stages mirror one-to-one (`00-INTAKE`…`04-TAILOR`; private half named `<stage>__YOUR_PRIVATE_INFO`). Per stage:

- **`ENGINE__PUBLIC_GIT_TRACKED/00-INTAKE/`** (public READMEs + template) + **`PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO/`** (your materials + generated intake state). Two input folders: **`01-about-you/`** (evidence — resumes, LinkedIn, held-role JDs, metrics, writing samples) and **`02-where-you-want-to-go/`** (direction — target/dream roles; shapes scoring/direction, but **never** becomes claims about your experience). Also holds the generated `materials-inventory.md` and `resume-assessment.md`.
- **`ENGINE__PUBLIC_GIT_TRACKED/01-INBOX/`** (public template) + **`PRIVATE__YOUR_FILES_GITIGNORED/01-INBOX__YOUR_PRIVATE_INFO/`** (your data) — active job URLs to rank. Paste one per line into the private **`paste-job-urls-to-rank-here.txt`** (a gitignored working copy, created from the tracked `.template.txt` on first run). Batch as many jobs as you've got in one sitting rather than trickling them in one at a time — vetting scores jobs in parallel, and ranking is most useful when it's comparing several real options against each other, not judging one job in isolation.
- **`ENGINE__PUBLIC_GIT_TRACKED/02-PREP/`** — **Prep.** Fetch each job URL into a clean job `.txt`: `prep_job_urls.py`, the Playwright fallback `prep_job_urls_playwright.py`, and the ATS-aware `ats_fetchers.py` (Greenhouse / Lever / Ashby / Workday / LinkedIn-guest). PII-free; no dependency on your profile.
- **`ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/`** (engine) + **`PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/`** (your scoring card + profile) — **Vet.** Triage only: score and rank which jobs are worth applying to, using your scoring card + candidate profile. Writes a ranked CSV + Markdown + a formatted XLSX. See `ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/CLAUDE.md`.
- **`ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/`** (engine + templates) + **`PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/`** (your instances) — **Tailor.** Resume *tailoring* only (never submitting). Writes an `application_resume_output - [Company] - [Role].md` draft: picks a resume base, flags gaps, suggests content. Engine spec: `ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/00-job_application_agent.md`.
- **`ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/learning/`** (spec + templates) + **`PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/learning/`** (your ledger/queue) — **Reconcile.** Post-submission learning loop (maintenance-only, never read during a generation run): compares what the system recommended against what you actually submitted and proposes lessons for your review. `reconcile-spec.md`, `learning-ledger.md`, `source-update-queue.md`.
- **`PRIVATE__YOUR_FILES_GITIGNORED/05-SUBMITTED-APPLICATIONS__YOUR_PRIVATE_INFO/`** — durable archive of submitted applications (gitignored; the default archive root, configurable in `jail.config.json`). After you submit an application, run **`/archive`** to *move* its folder here (never copied), then **`/reconcile`** later to learn from the final submitted version.
- **`__READY_TO_REVIEW__PRIVATE_GITIGNORED/`** — the human-review hub. Holds dated **job batches** (`MM-DD-YY/`) and other **review folders** (`MM-DD-YY - Intake Review/`, `MM-DD-YY - Source Update Review/`). Only exact date-shaped folder names (`MM-DD-YY`) are treated as job batches.

---

## Templates vs. generated instances vs. shared engine

- **Generated instances (gitignored — your personal data):** the bare-name files `/intake` (and, later, `/reconcile`) create — e.g. `jail.config.json`, `PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/01-scoring-card.md`, `PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/02-candidate-profile.md`, `PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/01-profile.md`, `PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/04-experience-bank.md`. **The engine reads these.**
- **Tracked templates (safe to commit):** the matching `*.template.md` / `*.template.json` files. `/intake` reads a template and writes the instance; it never fills a template in place.
- **Shared engine (don't personalize):** `ENGINE__PUBLIC_GIT_TRACKED/02-PREP/*`, `.claude/workflows/*`, `.claude/agents/*`, `ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/00-job_application_agent.md`, `ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/06c-skills-reconciliation-rules.md`, `ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/learning/reconcile-spec.md`, `ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/new_batch.py`, `ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/make_rankings_xlsx.py`, `docs/*`.

If a required instance is missing, the engine tells you to **run `/intake` first** rather than failing mysteriously.

---

## Setup — run this first

Run **`/intake`** before anything else. It reads your materials (from `PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO/01-about-you/` + `PRIVATE__YOUR_FILES_GITIGNORED/00-INTAKE__YOUR_PRIVATE_INFO/02-where-you-want-to-go/`, or pasted/attached in chat), asks a few targeted questions, and generates your instance files **from the templates**:

- `PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/01-scoring-card.md` — your rubric (4 weighted dimensions + 1–2 custom factors)
- `PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/02-candidate-profile.md` — who you are, your priority lanes, practical constraints
- `PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/01-profile.md`, `02-resume-index.md`, `03-approved-truths-and-boundary-rules.md` (optional), `04-experience-bank.md`, and — over time — the summary/skills quick references, bio library, and learning files.

Until intake has run, only the `.template.md` files exist and the pipeline has nothing personal to score or tailor against. Your resume base files live in **your own** resume folder (you point intake at it) — they are not stored in this repo.

---

## How to run (three modes)

First scaffold + fetch a batch: `python ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/new_batch.py <MM-DD-YY>`, then run the fetch commands it prints. Then pick a mode (`<batch>` = `__READY_TO_REVIEW__PRIVATE_GITIGNORED/<MM-DD-YY>`):

1. **Vet only (default):** `run-batch {folder: "<batch>"}` — vets and ranks into `1 - Rankings/`, then stops. You review the rankings and decide what to pursue.
2. **Vet + tailor top N:** `run-batch {folder: "<batch>", tailor: true, topN: 3}` — vets, then tailors resume drafts into `2 - Tailored Resumes/` for the top N (sequential, highest first, Skip-status excluded).
3. **Tailor a hand-picked set:** `tailor-jobs {jobs: ["<batch>/3 - Source Material/All Job Posts (full text)/jobA.txt", ...]}` — only the chosen jobs, in order. Use after a vet-only run.

Tailoring always runs the `job-applier` agent in autonomous mode: it never blocks on questions and puts a **"Questions for the candidate"** section at the top of each output for you to resolve.

### Where a run writes

Everything a run produces lands in one place: **`__READY_TO_REVIEW__PRIVATE_GITIGNORED/<batch>/`**, in numbered tiers so the review order is top-down by importance — `0 - Prep Report/` (prep's `prep-report.md` + `prep-manifest.json`), `1 - Rankings/`, `2 - Tailored Resumes/` (one `Company - Role` folder per tailored job), and `3 - Source Material/` (usable job posts in `All Job Posts (full text)/`; thin/failed quarantined in sibling `Needs Review/` and `Failed/`; plus a snapshot of that batch's URLs). The leading `__` pins the folder to the top of the repo. Nothing is moved after the fact; `ENGINE__PUBLIC_GIT_TRACKED/02-PREP/`, `ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/`, `ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/` hold only engine code + templates (your 04-TAILOR instances live under `PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/`), never run outputs.

---

## Scope guardrail

This pipeline prepares drafts and organizes folders. It must **never submit applications** — that step is outward-facing and irreversible, and stays a human decision.

---

## Working style for this repo

A local, git-tracked workspace — routine file changes are reversible, so optimize for momentum: read, search, and edit freely; don't pause to ask "should I continue?" after routine steps. Stop and ask first only when an action reaches outside the repo, needs secrets/credentials/payment, is truly destructive and hard to undo (`rm -rf`, force-push over shared history), or changes dependencies/CI.

---

## Known assumptions

- **Resume bases** can be Word (`.docx`), PDF, plain text/Markdown, or Apple Pages — point intake at whatever you use (Google Docs: export to `.docx`/PDF first). The Tailor step reads each format with the right tool (docx/pdf skills; `.txt`/`.md` directly; `.pages` via the bullet previews in the resume index) and copies the base in its native format, keeping the original extension.
- Python parts (`ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/new_batch.py`, `ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/make_rankings_xlsx.py`, `ENGINE__PUBLIC_GIT_TRACKED/02-PREP/`) need a local `.venv` with the deps in `requirements.txt` (notably `openpyxl` for the XLSX, and Playwright for the JS-rendered fetch fallback).

---

## Repo changelog

`docs/changelog.md` is this repo's own project history (separate from anything the pipeline produces for a user). Add a rough dated entry there during meaningful work; run `python3 scripts/doc_synthesis.py` to consolidate entries into readable threads and refresh `docs/v2-end-to-end-workflow.md`. See `scripts/README.md`.
