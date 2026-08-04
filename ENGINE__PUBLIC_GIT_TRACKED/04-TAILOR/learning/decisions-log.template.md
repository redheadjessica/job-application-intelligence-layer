# Decisions Log

Append-only, dated record of the candidate's OWN explicit rulings about their evidence and about how the tailoring system should behave.

**Everything here is FACT the moment it is recorded.** The candidate's confirmation IS the decision — nothing in this file waits for review, and nothing here is ever re-litigated back to the candidate. This is the durable home for the "observed content = fact, applied immediately" policy: when the candidate states a preference in chat, or when a bullet appears on a resume they told the system to reconcile, the decision lands here AND in the layer it governs, on the same pass.

**This is NOT the proposal queue.** `source-update-queue.md` holds the SYSTEM's *inferences* about what the candidate might want, which genuinely need a yes/no. This log holds the candidate's *own decisions*, already applied. The two never mix: a decision the candidate made is never downgraded to "needs review."

Every entry names the layer it governs so it stays traceable:
- **Evidence** = facts/bullets about the candidate (experience bank, `03*-canonical.md`, approved-truths, summaries, skills).
- **Behavior Rule** = how the pipeline/agents act (the `00` spec, agent files, routing, reconcile).

The reconcile/feedback pass reads this log to avoid re-proposing settled decisions, and echoes each new capture back in chat (never files silently).

## Format

```
### <MM-DD-YY> — <short title>
- **Decision:** <what the candidate ruled, in their words where possible>
- **Type:** Evidence | Behavior Rule | both
- **Applied to:** <file(s) edited>
- **Status:** applied | noted (already true / no edit needed) | superseded by <date>
```

---

<!-- New entries go below, newest first. -->
