# Source-Update Queue

Proposed edits to canonical generation files, awaiting human review. Produced by the reconcile workflow (`reconcile-spec.md`).

**This file is seeded empty.** Proposed edits accumulate here as you reconcile submitted applications.

**HARD RULE:** reconcile only **proposes** here. A human applies edits separately, after review. Nothing in this file is auto-applied. This is a maintenance file and is **not** read during a normal résumé-generation run.

## What this is

The review queue for the learning loop. When a reconcile finds a pattern concrete enough to imply a specific edit to a named canonical file (your profile, resume index, experience bank, summary/skills libraries, etc.), it drops a proposal here. Each proposal must clear a gate before a human applies it.

## Gate (when an item becomes review-ready)

Per `reconcile-spec.md` §9, an item graduates from `proposed` to `confirmed-ready-to-apply` only when **at least one** is true:
- you explicitly confirm it, or
- it recurs across **≥2** completed applications.

Even when ready, the actual edit to a canonical file is **always a separate, deliberate human action**. The gate promotes an item to "review me"; it never auto-applies. Single-occurrence items are **not** discarded — they are kept on the watch list and are promotable anytime on your confirmation (`reconcile-spec.md` §9a).

Status legend: `proposed` · `needs-confirmation` · `needs-2nd-occurrence` · `confirmed-ready-to-apply` · `applied` · `rejected`.

## Queue

_(none yet — proposals will be appended here by reconcile runs.)_

When the same proposal recurs, **increment its occurrence count and add the application** to the existing item — do not add a duplicate item.

Entry shape:

```
### [<status>] <target file> — <one-line change>
- **Proposed change:** <specific, concrete edit>
- **Rationale:** <why>
- **Evidence:** <applications supporting it> · **occurrences:** <N>
- **Status:** proposed | needs-2nd-occurrence | confirmed-ready-to-apply | applied | rejected
- **Source:** <reconcile-report path(s)>
```

## Watch list (single-occurrence — durably preserved, NOT moot)

Single-occurrence insights live here. They are kept indefinitely and stay retrievable; each is promotable now on your confirmation (you do not have to wait for a 2nd occurrence). Nothing here is discarded as "moot" (`reconcile-spec.md` §9a).

_(none yet.)_

## Base / template candidates (copy-don't-rebuild — confirmation-only, NOT subject to ≥2)

Finalized résumés that cleanly represent a role archetype. On your confirmation, register the **exact finalized résumé** as a canonical base in your resume index so future similar roles **copy it rather than rebuild**. One occurrence is enough; this path is never gated on recurrence (`reconcile-spec.md` §9a).

_(none yet.)_
