# Job Pipeline — a local AI co-pilot for your job search

This is a run-it-on-your-own-computer pipeline that turns the slog of job-hunting into one smooth flow: it **ranks** job postings against *your* criteria, then **drafts a tailored resume** for the ones worth your time. You stay in control of every word — **it never submits anything for you.**

You run it inside **Claude Code** (Claude that can work with files on your computer). If you've only ever used Claude in a browser, that's fine — this walks you through it.

**You'll need:** a Claude plan that includes Claude Code. As of this README's original authoring in June 2026, **Claude Pro is about $20/month** and is the simplest starting point. Plan on about 20–30 minutes the first time. Works on Mac and Windows.

**What you'll have at the end:** a ranked spreadsheet of the jobs you gave it, and — for your top pick — a **tailored resume draft (in Markdown) plus targeting notes** (which base to start from, gaps to address, suggested bullets and summaries), waiting in one folder, `__READY TO REVIEW/`. It's a working draft to build from, **not a polished Word / Pages / Google Docs file** — you finalize the formatting and wording in your own editor.

---

## Setup — six steps, once

### 1. Get the code onto your computer

Pick whichever fits you:
- **Download ZIP** (simplest) — click the green **`Code`** button on this page → **Download ZIP**, then unzip it somewhere you'll find it (your Desktop is fine). Best if you're not into GitHub and just want to try it locally.
- **Clone** — `git clone https://github.com/redheadjessica/job-pipeline-starter` (or use the GitHub Desktop app). Best if you're comfortable with git and want an easy way to pull future updates.
- **Fork** — only if you want your *own* GitHub copy to customize.

Whichever you pick, keep your **real job-search materials private and local** — if you ever fork publicly, don't put your actual resumes, notes, or rankings in it.
<!-- TODO: Add screenshot: GitHub Code → Download ZIP -->


### 2. Get Claude Code

Easiest is the **Claude desktop app**: download it from [claude.ai/download](https://claude.ai/download), install it, and sign in with your Claude account (Pro or higher).
*(Terminal person? Install the CLI: `curl -fsSL https://claude.ai/install.sh | bash` on Mac/Linux.)*

### 3. Open this folder in Claude

In the desktop app: open the **Code** tab → **Select folder** → choose the unzipped folder → pick **Local**.
**Quick check it worked:** type `/` in the message box. You should see **`/intake`** and **`/run-batch`** in the list. If they're there, you're set — they load automatically, nothing to install or enable.
*(Terminal: `cd` into the folder, run `claude`, then type `/`.)*
<!-- TODO: Add screenshot: Claude Code with the folder opened and /intake visible -->


### 4. Let Claude set up the helper scripts (one-time)

A couple of steps use small Python scripts (to pull down job posts and build the spreadsheet). Easiest: just tell Claude — **"Set up the Python environment for me."** It runs the setup and asks permission to install the bits it needs; **review and approve** when it does.
*(Savvy: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.)*

> **Before you add your real materials — a quick privacy heads-up.** A resume is usually fine to share, but a job-search *workspace* tends to hold a lot more: rough drafts, salary thinking, job rankings, private notes, who referred you, rejections, your whole application strategy. Keep all of that **local and private** — don't commit your personal job-search files to a public repo. (This repo is set up so you don't have to.)

### 5. Set the pipeline up for *you* — run `/intake`

Type **`/intake`** and follow along. Share your resume whatever way's easiest — **paste it right in the chat, attach it, or point Claude at a folder you already keep.** The more relevant material you share, the better the setup (intake tells you what helps). It reads everything, gives you an honest read on your resume, asks a few quick questions, and builds your personal files. About five minutes to "ready to rank jobs."

### 6. Add a few jobs, then rank + tailor

Open **`inbox/tonight-urls.txt`** and paste in a handful of job-posting links, one per line — even ones you've only glanced at. Then tell Claude: **"Start today's batch from my inbox and tailor my top job."**
*(Savvy: `python vetting/new_batch.py <today as MM-DD-YY>`, run the fetch command it prints, then `/run-batch {folder: "__READY TO REVIEW/<MM-DD-YY>", tailor: true, topN: 1}`.)*

A few minutes later, open **`__READY TO REVIEW/<today's date>/`**:
- **`1 - Rankings/`** — your jobs scored and sorted, with the reasons why.
- **`2 - Tailored Resumes/`** — your top job's **tailored draft + targeting notes**. Start here; finalize the wording in your own editor.
- **`3 - Source Material/`** — the job posts it pulled down.
<!-- TODO: Add screenshot: example __READY TO REVIEW/ output folder -->


That's the whole loop. From here, run it whenever you've collected a few new postings.

---

## Good to know

- **It never submits anything.** It drafts and organizes; sending an application is always your move.
- **It hands you a draft, not a final.** You get a strong starting point plus notes — you do the final polish in your own editor (Word, Google Docs, Pages, whatever you use).
- **It's honest with you.** Intake will tell you straight where your resume is weak. That's the point — it's here to help you get hired, not to flatter you.
- **Your materials, your workspace.** Your real resumes, notes, job descriptions, and outputs are meant to stay in your local/private workspace, not in a public repo. Claude will process the files you point it at, so only use materials you're comfortable using with your Claude account. This repo is structured so your personal job-search materials don't need to be committed or shared.
- **Mind how it's billed.** Depending on how your Claude Code is set up, it runs on either your Claude **subscription** or **API credits** — worth checking which *before* you kick off a big batch, since the costs add up differently. A single run is usually inexpensive.

## If `/intake` doesn't show up

Make sure you opened the **folder itself** (the one containing this README), not a parent folder, and that you chose **Local**. Type `/` again to refresh the list. Still stuck? Just tell Claude "I don't see the intake skill" and it can check the setup with you.

---

## About

Built by **Jessica Barnett**, a product leader and builder exploring practical AI workflows for job search, personal systems, and product work. No guarantees, no magic, no auto-applying — just a project I built during my own job search and decided to share.

**Feedback or suggestions?** [linkedin.com/in/redheadjessica](https://www.linkedin.com/in/redheadjessica/)
