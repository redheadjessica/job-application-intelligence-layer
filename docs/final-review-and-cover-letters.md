# Final review & cover letters

Short version: JAIL gets you to a strong, tailored resume draft. The last mile — final wording, formatting, and hitting submit — is yours. Cover letters have their own **optional module** that you set up once.

## Cover letters (optional module)

JAIL can write cover letters, but **only after it has learned your voice** — the whole point is a letter that sounds like you, not like AI. The module lives in [`ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/cover-letter/`](../ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/cover-letter/README.md):

1. **Set up once with `/cover-letter-intake`.** It studies your past letters and public writing, distills a voice spec, an exemplar set (your best real letter becomes the gold standard), an anecdote bank, and an optional writing-links key — and stages it all for your approval before anything is saved. Like everything personal in JAIL, these are gitignored instances; only blank templates are tracked.
2. **Then run `cover-letter {job: "<path to job .txt>"}`** on any job you're tailoring. It drafts in your voice, gates the draft through a deterministic lint (banned AI-tell phrases, link billboards, punctuation rules), scores it adversarially for Fit and Voice, revises surgically (an anti-smoothing lint blocks the classic AI failure of sanding your personality off), and packages a `.docx` paste source + a compact review packet with its open questions at the top.
3. **You still own the words.** Read the packet's Questions first, edit in your own editor, and submit as PDF. The agent's `_cl_work/final.md` stays frozen as the learning baseline: reconcile diffs it against your submitted PDF, and only lessons you explicitly confirm become rules for future letters.

If you don't do cover letters, skip all of this — nothing else depends on it.

## Final review is external and human-led
For a high-priority application, do a final pass outside JAIL — your own judgment, a trusted human, or another AI assistant (ChatGPT, Claude, whatever you use). JAIL gives you the structured materials and the reasoning; the final call on wording and fit is yours.

## The generated markdown is a draft, not your final resume
`application_resume_output - … .md` is the agent's **recommendation** — base choice, suggested bullets, summary options, skills line, and open questions. You build the actual resume from it in your own editor (Word, Google Docs, Pages). The markdown is not, by itself, the thing you submit.

## The final submitted PDF matters later
When you submit, save the **final submitted resume as a PDF** into the job folder before you `/archive` it (and the final cover letter PDF too, if you wrote one). Reconcile learns by comparing the agent's recommendation against that final PDF, so the PDF (not the draft) is the ground truth. A `.pages`/`.docx` without an exported PDF isn't enough.

## JAIL never submits
Sending the application is always your move — through the company site, an ATS, LinkedIn, or email. JAIL drafts and organizes; it does not apply for you.
