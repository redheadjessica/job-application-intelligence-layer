---
name: revise-cover-letter
description: Revise ONE existing cover letter using the candidate's targeted feedback, with the agent (not the chat assistant) doing the writing and the full verify loop. Captures the feedback into the cover-letter canon first (§0 fact-vs-inference), then runs the cover-letter workflow in REVISE-WITH-FEEDBACK mode — writer revises → dual eval (fit + voice) → surgical finalize + .docx + link QA — versioning the result (never overwriting the original). Use whenever the candidate has read a letter and wants it reworked against specific notes.
---

# Revise a cover letter with targeted feedback

The candidate has an existing cover letter for a job and specific feedback on it. Your job is NOT to hand-write the new letter in chat — it is to (1) capture the feedback durably so it improves every future letter, then (2) hand the rewrite to the `cover-letter-writer` agent and run the verify loop, so the mechanism (not you) produces the letter and nothing evaporates when the session ends.

**Why this skill exists:** rewriting a letter against feedback kept happening ad hoc, with the chat assistant writing the letter directly and the feedback never landing in canon. That skips the eval pass and loses the lesson. This skill makes the loop deterministic.

## Prerequisites

- The cover-letter system is set up (`PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/cover-letter/` instances exist — run `/cover-letter-intake` first if not).
- The job's résumé tailoring is already done (never run the cover-letter step before the résumé for that job — see the sequencing rule in memory/canon).
- An existing letter for the job (a `final*.md` in the job folder's `_JAIL Agent Work/`). If there is none, this is a first draft — use the plain `cover-letter` workflow instead.

## Steps

### 1. Locate the job folder and the letter being revised
Find the job folder under `__READY_TO_REVIEW__PRIVATE_GITIGNORED/<batch>/2 - Tailored Resumes/<Company - Role>/`. Confirm the job `.txt` (the JD capture) and the most recent letter (`_JAIL Agent Work/final-v*.md`, highest number, else `final.md`). Read the current letter and the JD so you understand what the feedback is reacting to.

### 2. Capture the feedback into canon FIRST (§0 — the candidate's words are FACT, applied now)
The candidate's chat feedback is fact, not a proposal. Before running the writer, route each piece to where it durably belongs, and **surface each capture in chat** (one line: what you captured → which file):
- **Generalizable rulings about voice/positioning/what-to-lead-with** → append a dated entry to `PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/cover-letter/feedback-ledger.md` (the writer + evaluator read it every run; newest wins). Example: "lead leadership roles with the full leadership arc," "name OKR experience when the JD asks," "don't over-acknowledge a domain gap the résumé already handles."
- **New personal stories / lived details or a reframe of an existing one** → `cover-letter/anecdote-bank.md` (her own words enter directly, tagged with source + date).
- **A new/changed experience claim about her career** → the résumé canon (`04-experience-bank.md` cluster, or `03-approved-truths-and-boundary-rules.md` for a boundary), respecting existing truth boundaries. Log it in `learning/decisions-log.md`.
- Do NOT invent or overclaim. If something she said conflicts with a truth boundary (e.g. a RIDG client industry, or formal PM direct reports), honor the boundary and note the tension for her rather than encoding an overclaim.

### 3. Run the writer + verify loop (the agent writes, not you)
Invoke the cover-letter workflow in REVISE-WITH-FEEDBACK mode. Consolidate the candidate's feedback into one clear brief and pass it as `feedback`; point `out` at the existing job folder and `job` at the JD `.txt`:

```
Workflow({ name: "cover-letter", args: { job: "<path to the job .txt>", out: "<the job folder>", feedback: "<the candidate's consolidated targeted feedback, verbatim intent>" } })
```

The workflow will: revise the latest letter into the next `final-v<N>.md` (never overwriting the original — that immutable baseline is what `/reconcile` diffs against), run the adversarial fit + voice eval, apply surgical fixes, build the `.docx`, QA the links, and write a compact review packet. Optionally pass `baseline: "<path>"` to pin exactly which letter to revise.

### 4. Report
Relay: the new version's `.docx` + packet path, the fit/voice scores, any "Questions for you" the packet surfaced, and a one-line summary of what you captured into canon in step 2. Deliver the letter as files in the job folder — do not paste the full letter text into chat.

## Guardrails
- **Never overwrite an original** `final.md`/`.docx`/packet — every revision is a new version (protects the reconcile learning baseline).
- **The agent does the writing.** Don't draft the letter yourself in chat and skip the eval pass — that's the exact failure mode this skill removes.
- **Capture before you run**, so the writer's canon read in step 3 already includes the new rulings.
- This skill prepares a draft; it never submits. Submission stays the candidate's step.
