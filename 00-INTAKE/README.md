# Intake — set the pipeline up for yourself

Run **`/intake`** once before vetting or tailoring. It reads your career materials, gives you an honest read on them, asks a few questions, and generates your personalized files so the rest of the pipeline works for you. The more *relevant* material you share, the better — as long as it's sorted into the right buckets (mixing them is how a resume tool starts lying).

## What to share — three families, kept separate

**1. About you (the facts):** your resumes (every version — old or rough is fine), your LinkedIn experience, brag/wins docs, performance reviews — and, if you have them, **job descriptions for roles you've actually held** (a past or current job's posting describes your real work in an employer's words). This builds your profile and experience bank.

**2. Where you're headed (direction):** job descriptions for roles you're **genuinely reaching for**. These shape your scoring rubric — your lanes and what excites you — and they're *never* treated as your skills. Wanting a role doesn't put its requirements on your resume.

**3. Your voice:** writing samples, a portfolio, published work — used only for voice and credibility.

**Where they go:** families 1 and 3 (about you + your voice) go in `00-INTAKE/01-about-you/`; family 2 (direction) goes in `00-INTAKE/02-where-you-want-to-go/`. Each folder has a short README.

> A job description only counts as *your experience* if you held that role. Intake will confirm which is which before using any of them — it never guesses.
>
> **Not here:** the jobs you're vetting tonight. Those go in `01-INBOX/paste-job-urls-to-rank-here.txt` and get *scored* by the pipeline — intake assumes nothing about you from them.

## How to share it — whatever's easiest

- **Paste or attach right here in the chat** — the simplest, no files to move.
- **Point intake at a folder you already keep** (e.g. your existing resume folder) — it's read-only; your files are never moved or edited.
- **Drop files into the intake folders:** evidence about you in `00-INTAKE/01-about-you/`; roles you're aiming for in `00-INTAKE/02-where-you-want-to-go/` (direction only — each folder has a short README).
- **Give URLs** for public writing or a portfolio — intake fetches them for you.
- **LinkedIn:** export it (on your profile, **More → Save to PDF**, or **Settings → Get a copy of your data**) and share the file — intake will walk you through it. (LinkedIn blocks profile scraping, so export is the reliable path.)

Anything you share stays local: the `00-INTAKE/01-about-you/` and `00-INTAKE/02-where-you-want-to-go/` folders, the generated `resume-assessment.md`, and your filled source files are all gitignored, so your personal data is never committed.

## Then run `/intake`

It works in two tiers — **Tier 1** gets you ranking jobs in ~5 minutes; **Tier 2** goes deeper so it can draft tailored resumes. You can stop after Tier 1 and come back.

It will be honest with you about your materials. That's the point — it's here to help you get hired, not to flatter you.
