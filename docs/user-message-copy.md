# User-message copy deck (voice reference)

A reference for the chat language JAIL uses at each step, so intake, prep, ranking, tailoring, archive, and reconcile all sound the same. This is **not** wired into code — the skills and workflows generate their own messages; this is the canonical voice to keep them consistent. Tone: plain, specific, helpful, a little human. Not over-polished, not corporate.

> Where each currently lives: intake → `.claude/skills/intake/SKILL.md`; prep → `02-PREP/prep_common.py` (stdout) + `prep-report.md`; ranking → `.claude/workflows/vet-jobs.js`; archive → `.claude/skills/archive/SKILL.md`; reconcile → `.claude/workflows/reconcile.js`. Keep those in this voice.

## Intake — review ready
> Your intake review is ready in `__READY TO REVIEW/<MM-DD-YY> - Intake Review/`. Start with `START HERE.md`, then open the files in order. Look for anything wrong, missing, overstated, or just not-you. Easiest way to give feedback: talk it back to me here (voice-to-text is great). You can also edit the files directly — tell me when you're done and I'll reread them. Nothing is saved to your source of truth until you approve.

## Intake — approved / promoted
> Done. I've written your source-of-truth files (scoring card, profile, experience bank, summaries, skills, preferences). They're private and gitignored. You can rank jobs now — paste a few links into `01-INBOX/paste-job-urls-to-rank-here.txt` and tell me to start a batch.

## Missing generated source file
> I can't do that yet — your `<file>` hasn't been generated. That happens when you run `/intake`. Run `/intake` first, then re-run this.

## Prep — finished (clean)
> Prepared 12 usable job posts. No duplicates, nothing failed. Ready to rank.

## Prep — finished (with issues)
> You gave me 26 URLs. I prepared 23 usable job posts. 1 was a duplicate, and 2 came back too thin after a retry — I quarantined those so they don't pollute your rankings (`3 - Source Material/Needs Review/` and `Failed/`). Paste the full text for those if you want them in. Otherwise, ready to rank the 23.

## Thin / failed quarantined
> 2 posts were too thin or failed to fetch and were kept OUT of ranking (in `Needs Review/` and `Failed/`). Open them, paste the real job text if you have it, and re-run prep to pick them up.

## Ranking — complete
> Ranked 23 jobs. Open `1 - Rankings/` — the spreadsheet is the easy view, with comp, location, and lane fit colored to your own preferences. Tell me which ones you want to tailor. If anything looks obviously misranked, say so — that helps your future scoring.

## Tailoring — complete
> Tailored your top 3 into `2 - Tailored Resumes/`. Each folder has a draft (`application_resume_output - … .md`) — start with the "Questions for the candidate" section at the top. These are drafts to build from in your own editor, not finished resumes.

## Final-review reminder
> Before you send a high-priority one, do a final pass — your own read, a trusted human, or another AI. JAIL gives you the materials; the final wording and the decision to submit are yours.

## Archive — missing final PDF
> I found the generated resume output, but I don't see a final submitted PDF. If you edited the resume before submitting, reconcile needs that final version. Want to add it before I archive this, or should I move it without the PDF for now?

## Archive — complete
> Archived `<Company - Role>` to `<archive path>`. Moved, not copied — it's out of `__READY TO REVIEW` now. Reconcile hasn't run; when you're ready, run `/reconcile` so JAIL can learn from the final submitted version.

## Reconcile — suggested
> This is archived. No rush, but once you've got a few submitted, run `/reconcile` so JAIL can learn what you actually changed and get sharper.

## Reconcile — complete
> Reconciled 3 submitted applications. I logged what you changed vs. what I recommended, added the finalized summaries to your library, and put any proposed source-file updates in the queue for your review. I didn't touch your core files — those are yours to approve.

## Live-test / dependency caveat
> Heads up: this part needs the Python environment set up. Say "set up the Python environment" and I'll walk through it. (It's what pulls down job posts and builds the spreadsheet.)
