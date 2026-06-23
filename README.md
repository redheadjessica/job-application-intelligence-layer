# Job Pipeline — a local AI co-pilot for your job search

This is a run-it-on-your-own-computer pipeline that turns the slog of job-hunting into one smooth flow: it **ranks** job postings against *your* criteria, then **drafts a tailored resume** for the ones worth your time. You stay in control of every word — **it never submits anything for you.**

You run it inside **Claude Code** (Claude that can work with files on your computer). If you've only ever used Claude in a browser, that's fine — this walks you through it.

**You'll need:** a Claude plan that includes Claude Code (**Claude Pro, ~$20/month**, is the simplest), and about 20–30 minutes the first time. Works on Mac and Windows.

**What you'll have at the end:** a ranked spreadsheet of the jobs you gave it, and — for your top pick — a **tailored resume draft plus targeting notes** (which base to start from, gaps to address, suggested bullets and summaries), all waiting in one folder, `__READY TO REVIEW/`. You finalize the wording in your own editor.

---

## Setup — six steps, once

### 1. Get the code onto your computer

On this page, click the green **`Code`** button → **Download ZIP**, then unzip it somewhere you'll find it (your Desktop is fine). No account or command line needed.
*(Comfortable with git? `git clone https://github.com/redheadjessica/job-pipeline-starter` instead. Or use the GitHub Desktop app. Any of the three works.)*

### 2. Get Claude Code

Easiest is the **Claude desktop app**: download it from [claude.ai/download](https://claude.ai/download), install it, and sign in with your Claude account (Pro or higher).
*(Terminal person? Install the CLI: `curl -fsSL https://claude.ai/install.sh | bash` on Mac/Linux.)*

### 3. Open this folder in Claude

In the desktop app: open the **Code** tab → **Select folder** → choose the unzipped folder → pick **Local**.
**Quick check it worked:** type `/` in the message box. You should see **`/intake`** and **`/run-batch`** in the list. If they're there, you're set — they load automatically, nothing to install or enable.
*(Terminal: `cd` into the folder, run `claude`, then type `/`.)*

### 4. Let Claude set up the helper scripts (one-time)

A couple of steps use small Python scripts (to pull down job posts and build the spreadsheet). Easiest: just tell Claude — **"Set up the Python environment for me."** It runs the setup and asks permission to install the bits it needs; say yes.
*(Savvy: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.)*

### 5. Set the pipeline up for *you* — run `/intake`

Type **`/intake`** and follow along. Share your resume whatever way's easiest — **paste it right in the chat, attach it, or point Claude at a folder you already keep.** The more relevant material you share, the better the setup (intake tells you what helps). It reads everything, gives you an honest read on your resume, asks a few quick questions, and builds your personal files. About five minutes to "ready to rank jobs."

### 6. Add a few jobs, then rank + tailor

Open **`inbox/tonight-urls.txt`** and paste in a handful of job-posting links, one per line — even ones you've only glanced at. Then tell Claude: **"Start today's batch from my inbox and tailor my top job."**
*(Savvy: `python vetting/new_batch.py <today as MM-DD-YY>`, run the fetch command it prints, then `/run-batch {folder: "__READY TO REVIEW/<MM-DD-YY>", tailor: true, topN: 1}`.)*

A few minutes later, open **`__READY TO REVIEW/<today's date>/`**:
- **`1 - Rankings/`** — your jobs scored and sorted, with the reasons why.
- **`2 - Tailored Resumes/`** — your top job's **tailored draft + targeting notes**. Start here; finalize the wording in your own editor.
- **`3 - Source Material/`** — the job posts it pulled down.

That's the whole loop. From here, run it whenever you've collected a few new postings.

---

## Good to know

- **It never submits anything.** It drafts and organizes; sending an application is always your move.
- **It hands you a draft, not a final.** You get a strong starting point plus notes — you do the final polish in your own editor (Word, Google Docs, Pages, whatever you use).
- **It's honest with you.** Intake will tell you straight where your resume is weak. That's the point — it's here to help you get hired, not to flatter you.
- **Your data stays yours.** Your resume and materials live only on your computer; the repo is set up so they're never committed or shared.
- **It costs something to run.** Claude Code uses your Claude plan (or API credits) — a normal session is inexpensive, but it isn't free.

## If `/intake` doesn't show up

Make sure you opened the **folder itself** (the one containing this README), not a parent folder, and that you chose **Local**. Type `/` again to refresh the list. Still stuck? Just tell Claude "I don't see the intake skill" and it can check the setup with you.
