# Cover Letter System

Generates cover letters in **your** voice through a **draft → lint → dual eval → surgical revise →
package** loop, so every letter arrives ready for review with a scorecard instead of needing an
endless chat back-and-forth.

Like everything in JAIL: tracked `*.template.md` files are the blank mechanism; your filled,
personal versions are gitignored bare-name instances. Run **`/cover-letter-intake`** first — it
interviews you, studies your past letters, and stages your voice spec, exemplars, anecdote bank,
and config for approval. The engine reads only the instances.

## How to run it

```
cover-letter {job: "__READY_TO_REVIEW__PRIVATE_GITIGNORED/<batch>/3 - Source Material/All Job Posts (full text)/foo.txt"}
cover-letter {jobs: ["...a.txt", "...b.txt"]}
cover-letter {job: "...foo.txt", out: "path/to/an/existing/Company - Role folder"}
```

Output lands in the job's `Company - Role` folder (created in the batch's `2 - Tailored Resumes/`
if needed, or wherever `out` points):

- **`<Your-Name>-CoverLetter - Company - Role.docx`** — the deliverable. Open it, select all,
  copy, and paste into your own letter template with a formatting-preserving paste (in Pages:
  regular **Paste**, never "Paste and Match Style" — it strips the inline links). Styling per
  `formatting-spec.md` + `config.json`.
- **`application_coverletter_output - Company - Role.md`** — the review packet: Questions for you
  at top, fit/voice scorecard, links used and why, and the paste checklist.
- `_cl_work/` — intermediates (draft-v1, evaluations, final.md). `final.md` is the reconcile
  baseline; leave it alone.

## The loop

1. **Draft** — the `cover-letter-writer` agent writes from `voice-spec.md` + `feedback-ledger.md` +
   your exemplars + `writing-links.md` (the only link source), gated by `lint_cover_letter.py`
   (banned phrases, punctuation, link billboards, AI fingerprints — all deterministic, zero tokens).
2. **Evaluate** — the `cover-letter-evaluator` agent scores Fit (against the JD's real priorities)
   and Voice (against your canon) per `eval-rubric.md`, compares against your GOLD exemplar, and
   must argue against its own scores before finalizing.
3. **Revise** — the writer applies must-fixes surgically. The lint's preservation mode (`--prev`)
   mechanically blocks smoothing: removed exclamation points, vanished links, and flattened
   sentence rhythm are errors. One revision cycle; remaining concerns become flags for you,
   not more loops (endless polishing converges on exactly the AI voice this system exists to avoid).
4. **Package** — .docx generation, link QA (curl + writing-links verification), review packet.

## Church and state (the learning rule)

- **`_cl_work/final.md` is FROZEN once the loop completes.** It is the learning baseline:
  reconcile diffs it against your submitted PDF, and that diff must show YOUR edits only.
  Any later revision — a v3, a new-paragraph request, anything — is a NEW file
  (`_cl_work/final-vN-proposal.md` + a `- vN.docx` beside the original), never an overwrite. If
  you submit from a vN, reconcile still diffs against the original `final.md`; the proposal
  files show which changes were agent-assisted.
- **You never edit the .docx.** It is always the agent's verbatim output. Your edits happen in
  your own editor; **the version you submit is always a PDF.** The baseline-vs-PDF delta IS your
  feedback.
- Reconcile writes plain-English candidates to `feedback-queue.md`: "You did Y on the [Company]
  letter — on purpose? Make it the default?"
- Only you promote candidates into `feedback-ledger.md`, which is what the writer and evaluator
  actually read. Generation never learns from its own drafts, and never from unconfirmed
  inferences.

## Files

| File | Consumer | Job |
|---|---|---|
| `config.json` | lint + docx generator | your signature name, lint knobs, .docx styling (from `config.template.json`) |
| `voice-spec.md` | writer | your voice canon (distilled from your letters + feedback) |
| `eval-rubric.md` | evaluator | scoring anchors, comparison pass, self-pushback, findings rules |
| `feedback-ledger.md` | writer + evaluator | your confirmed feedback; newest wins over everything |
| `feedback-queue.md` | reconcile → you | unconfirmed candidate lessons; never read at generation |
| `anecdote-bank.md` | writer + evaluator | your indexed true stories (the only story source) |
| `writing-links.md` | writer + evaluator | your published-work link index (the only URL source; optional) |
| `exemplars/` | writer + evaluator | your annotated real letters (one GOLD; see `exemplars/README.md`) |
| `lint_cover_letter.py` | writer (gate) | deterministic rules + anti-smoothing preservation mode |
| `make_cover_letter_docx.py` | package step | markdown → formatted .docx (needs `python-docx`, in the venv) |
| `formatting-spec.md` | generator + you | the .docx formatting contract |

## Maintaining

- New feedback from you → add an entry to `feedback-ledger.md` (dated, plain English, example).
- A personal mechanical rule (a phrase you never use, a tell you've spotted) → add it to
  `config.json` → `lint.extra_banned_phrases` AND note it in your `voice-spec.md` hard-rules list.
  (A rule that's a universal AI tell, not personal taste, belongs in `lint_cover_letter.py` itself —
  PRs welcome.)
- A new writing sample/link target → add it to `writing-links.md` (never a second link registry).
- Paste/formatting friction → fix `formatting-spec.md` + `config.json` together.
