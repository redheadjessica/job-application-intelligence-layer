# JAIL — public page copy (handoff for the website repo)

**Purpose:** suggested copy for the `redheadjessica.com/jail` page. **The website source lives in a separate repo — this file does not touch it.** Hand this to the agent working in the website repo as the source copy; trim/adapt to the site's design.

**Voice:** direct, specific, human, a little sharp. Not corporate, not AI-tool hype. Keep the honesty — the "what it doesn't do" section is load-bearing, don't cut it for marketing. No pricing claims. Author attribution + proof-point framing stay.

---

## Proposed page structure
Hook → What JAIL is → Why it exists → What it does → What it doesn't do → Who it's for → How to try it → Privacy / local-first → Built by Jessica → Links + screenshots.

---

## Page copy

### Hook
Applying to jobs is a grind: the same resume, fifty tweaks, and no real sense of which roles are even worth the effort. JAIL is the local workflow I built to make that grind faster and a lot less miserable — without lying on a resume to do it.

### What JAIL is
JAIL (Job Application Intelligence Layer) is a run-it-on-your-own-computer workflow for Claude Code. You give it a batch of job links and your real career history; it ranks the roles against what you actually want, picks the strongest resume base for each, and hands you a tailored draft plus honest notes on where you fit and where you're stretching. You keep control of every word. It never submits anything.

### Why it exists
I built it during my own job search, for myself, because the tools out there either auto-spam applications or write confident fiction onto your resume. I wanted something fast and honest that kept my judgment in the loop. It worked well enough that I cleaned it up and made it public.

### What it does
- Ranks a batch of jobs against your priorities — pay, location, the lanes you actually want — and shows you why each scored the way it did.
- Picks the best resume base per role and drafts tailored bullets, summaries, and a skills line from your real experience.
- Flags gaps and weak claims instead of papering over them.
- Keeps everything in one review folder, and learns from what you actually submit over time.

### What it doesn't do
- It doesn't find or scrape jobs for you — you bring the links.
- It doesn't auto-apply or submit anything. Ever.
- It doesn't write cover letters (yet).
- It doesn't hand you a finished Word/Pages file — you get a strong draft and finish it in your own editor.
- It doesn't guarantee interviews, and it won't invent experience to make you look better.

### Who it's for
People running a real, considered job search who want leverage without losing the truth — and who are okay running something locally in Claude Code. You don't need to be an engineer; you do need to follow a setup once.

### How to try it
1. Get the repo: github.com/redheadjessica/job-application-intelligence-layer (Download ZIP or clone).
2. Open the folder in Claude Code.
3. Run `/intake` once to set it up from your resume.
4. Paste in some job links and let it rank and tailor.

Full setup is in the repo README.

### Privacy / local-first
JAIL runs on your machine. The repo ships templates and workflow code — never anyone's data. The files it generates from your resume, your raw materials, and your submitted applications are all gitignored, so your private job-search data stays on your computer and out of git by default. If you fork it, keep the fork private.

### Built by Jessica
I'm Jessica — I build practical AI workflows for product and personal systems. JAIL is one of them: a real tool I used in my own search, built end-to-end with AI assistance, and shared as a proof point that this kind of applied AI building is worth doing carefully. Feedback welcome.

---

## Links (use the repo's actual links)
- GitHub: `github.com/redheadjessica/job-application-intelligence-layer`
- LinkedIn: `linkedin.com/in/redheadjessica`

## Screenshot placeholders (synthetic "Jordan Lee" persona — see `docs/screenshots/screenshots-plan.md`)
- `[shot: ranking-xlsx]` — the ranked spreadsheet (the payoff visual)
- `[shot: intake-review]` — the staged intake review
- `[shot: tailored-output]` — a tailored draft with its Questions section
- `[shot: folder-tree]` — the review folder

## Implementation notes for the website agent
- This is suggested copy — trim and adapt to the site's design and length.
- Keep the "what it doesn't do" section; it's the credibility, not a disclaimer to bury.
- Don't add pricing claims.
- Keep author attribution + the proof-point framing.
- Screenshots use the synthetic "Jordan Lee" persona only — never real job-search data.
