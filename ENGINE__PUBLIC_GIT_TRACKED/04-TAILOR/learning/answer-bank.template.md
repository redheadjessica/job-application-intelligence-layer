<!-- TEMPLATE — copy structure only. /reconcile creates and appends the gitignored instance
     answer-bank.md (spec §13, answers lane). Harvest-only: no baseline exists for answers. -->
# Answer Bank — harvested application Q&A, keyed by archetype

Question+answer pairs harvested by reconcile from submitted applications. Seeds future answer
drafting; never read during resume tailoring.

Maintenance rules:
- **Reconcile is the sole writer.** Entries come from `_extracted/submitted-answers.txt` only —
  the candidate's own submitted words.
- **Key by archetype** (why-this-company, concept-to-shipped-tradeoff, how-you-use-AI, …); create
  a new `##` archetype heading only when no existing one fits.
- **Condense answers over ~150 words** to the argument + anecdote slugs (slugs reference
  `PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/cover-letter/anecdote-bank.md`); short answers stay verbatim.
- Note which parts are company-specific (to strip on reuse).
- Idempotent: one entry per question per company; re-runs never duplicate.

---

## {{archetype-slug}}

**Q: "{{the question as asked}}"** ({{Company}} — {{Role}}, {{date}})
Argument (condensed): {{the answer's argument; anecdotes by slug; company-specific bits flagged}}
