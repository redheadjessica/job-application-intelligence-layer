---
name: archive
description: Move a SUBMITTED application's folder out of the __READY TO REVIEW workspace into the durable, private submitted-applications archive (default 05-SUBMITTED-APPLICATIONS/<year>/). Runs a readiness check, warns clearly if the final submitted resume PDF is missing or ambiguous, moves (never copies), and writes a short archive-summary.md. Only on the user's explicit instruction. Never submits anything; never runs reconcile.
---

# Archive a submitted application

You move ONE completed application's folder from the review workspace into the user's durable archive, so the active `__READY TO REVIEW/` area stays clean and the submitted record is preserved for later learning (`/reconcile`).

## North star

The **submitted application record is the durable source of what actually happened.** The generated `application_resume_output*.md` is a draft, NOT the final submitted resume — the user usually edits the resume outside JAIL before submitting, so **the final submitted PDF is the thing that matters.** Move that record safely; never pretend you know what was submitted unless the file is there.

## When to run

**Only on the user's explicit instruction** that an application was submitted / should be archived — e.g. "I submitted the Headway one, archive it", "move this completed job to submitted applications", "/archive". Do **not** archive a folder just because a tailored draft exists. If it's unclear which application they mean, ask.

## Step 1 — Locate the folder

The usual source is a job folder under `__READY TO REVIEW/<MM-DD-YY>/2 - Tailored Resumes/<Company - Role>/`. Accept an explicit folder path if the user points at one. If multiple folders could match, list them and ask which. Do **not** assume every folder under `2 - Tailored Resumes/` was submitted.

## Step 2 — Resolve the archive path (config-aware)

- Read `jail.config.json` → `archive.path`. If missing/invalid, fall back to **`05-SUBMITTED-APPLICATIONS`** and **say so** in chat.
- **Year subfolder:** use the submission date if it's clear (the batch date `MM-DD-YY` → `20YY`, or a date in the folder name). If ambiguous, use the current year (`date +%Y`) and note it in the summary.
- Destination: `<archive.path>/<YYYY>/<Company - Role - date>` (keep the existing readable folder name; the archive convention is `Company - Role - MM-DD-YY`).

## Step 3 — Readiness check

`ls` the folder and classify what's there.

**Required:**
- `application_resume_output*.md` (the agent's recommendation)
- **the final submitted resume PDF** (see the heuristic below)
- the scraped job post / source job text (`.txt`, or the JD PDF)

**Optional (archive whatever's present):** cover letter, application answers, notes, recruiter/referral messages, screenshots, confirmation email.

**Final-PDF heuristic** — among the `*.pdf` files in the folder, set aside the obvious job-description/source PDF (named like the posting, or matching the scraped JD). Of the rest:
- prefer a PDF whose name contains "resume"; otherwise
- **exactly one** plausible resume PDF → accept it as the final submitted resume;
- **zero** → stop and warn (Step 4);
- **more than one** → stop and ask which is the final submitted version.
- A `.pages` / `.docx` alone is **not** sufficient as the final unless the user explicitly confirms that is what they submitted.

## Step 4 — If the final submitted PDF is missing or ambiguous

Do **not** silently archive. Say, clearly:

> "I found the generated resume output, but I don't see a final submitted PDF. If you edited the resume before submitting, reconcile needs the final version. Want to add it before I move this to the archive, or confirm you want it archived without the final PDF?"

(For multiple PDFs: ask which one is the final submitted resume.) Archive without the final PDF **only on explicit confirmation**, and note in `archive-summary.md` that **reconcile will be limited until the final submitted PDF is added.**

## Step 5 — Move (never copy)

- `mkdir -p "<archive.path>/<YYYY>"` (quote paths — they contain spaces).
- **`mv`** the whole folder into the year folder. Never copy — after the move the original must no longer exist under `__READY TO REVIEW/`.
- **Never overwrite.** If a folder with that name already exists in the archive, append a deterministic suffix (`-2`, `-3`, …) to the destination name.

## Step 6 — Write `archive-summary.md`

Inside the moved folder, write `archive-summary.md` from `.claude/skills/archive/archive-summary.template.md`, filling in: company, role, submitted date (if known), source batch/date, original source path, archive path, files present, files missing, final-PDF path, whether reconcile has been run (no, not yet), and the next recommended action. Keep it short and useful — a summary, not a checklist.

## Step 7 — Keep the workspace clean (mention, don't act)

After the move, glance at the source batch's `2 - Tailored Resumes/` for other **completed-looking** folders (ones that contain a final resume PDF). If any remain, gently mention them:

> "I see N other completed-looking folder(s) still in `__READY TO REVIEW`. If those were submitted too, tell me and I'll archive them."

Never auto-move anything the user didn't name.

## Step 8 — Suggest reconcile (don't run it)

Reconcile is a separate, manual, explicit step. After archiving, offer:

> "This is archived at `<path>`. When you're ready, run `/reconcile` so JAIL can learn from the final submitted version. (No rush — reconcile is most useful after your first few applications, after a meaningfully changed final resume, or when a new resume base emerges.)"

Do **not** run reconcile without explicit approval.

## Chat UX (always)

Tell the user, plainly: what you found (required + optional files, what's missing), what you're about to move and where, anything that needs their confirmation (a missing/ambiguous PDF), what happened, where the archive now lives, that reconcile was **not** run, and the next sensible action.

## Guardrails

- **Move, not copy.** One record, one place.
- **Never overwrite** an existing archived folder — suffix instead.
- **Explicit instruction required** — never archive on your own initiative.
- The archive is **private and gitignored** — it holds the user's real submitted materials.
- **Never run reconcile here**, and never submit anything.
