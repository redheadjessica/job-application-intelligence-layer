# Resume Index

This file is the **routing layer** for resume selection: it maps role archetypes → which resume base to start from → which evidence modules to pull, plus the governance and merge rules that keep the set coherent over time.

It is a practical working index, not a perfect historical catalog. Its job is to help you choose the best prior resume base quickly and consistently, then know what to graft into it.

Weight **more recent** applications more heavily than older ones. Group your bases by:
- company type
- role title / level
- domain
- likely hiring priorities
- resume framing needs

> **How to fill this file (intake).** This is a registry that points at *your own* finished resumes.
> You maintain it; the generation run reads it during base selection. Start by listing 3–8 of your
> strongest recent resumes as **named anchors** (below), then fill the **archetype → base → evidence**
> table so each role type routes to one starting point. Every `{{PLACEHOLDER}}` below is something you
> supply from your resume history.

---

## Primary Named Anchors — evaluate these first

<!-- intake: List your newest, strongest finished resumes here — the ones you'd actually start a new
     application from. For each, give: the role/level it was built for, the file path to the base, what
     it's "best for," its summary essence, and its skills lean. Keep 3-8. Evaluate the WHOLE set
     against a target role and pick the strongest strategic match — do NOT auto-default to one. -->

These are your newest completed resumes and the **primary** bases. **Evaluate the whole set** against the role and pick the strongest strategic match — do **not** auto-default to any single one. A base is a **layout + positioning starting point, not a mandate to keep its bullets** — swap bullets freely to build the strongest portfolio. **When you choose, briefly explain why the chosen base is strongest versus the other anchors.**

### {{PLACEHOLDER — anchor name, e.g. "Company A — Role/Level (date)"}}
Base file: `{{PLACEHOLDER — path to your resume base file for this anchor}}` **Best for:** {{PLACEHOLDER — the role types / domains this anchor wins}} Summary essence: {{PLACEHOLDER — one-line gist of this resume's summary/positioning}} Skills lean: {{PLACEHOLDER — the skills line emphasis this base carries}} Evidence notes: {{PLACEHOLDER — which experience bullets/modules this base leads with, and any quirks to neutralize when reusing it for a different company}}

### {{PLACEHOLDER — second anchor name}}
Base file: `{{PLACEHOLDER — path to your resume base file for this anchor}}` **Best for:** {{PLACEHOLDER — the role types / domains this anchor wins}} Summary essence: {{PLACEHOLDER — one-line gist}} Skills lean: {{PLACEHOLDER — skills line emphasis}} Evidence notes: {{PLACEHOLDER — leading modules + reuse caveats}}

<!-- intake: copy the block above for each additional anchor. -->

### Older anchors (valid, but not the default)
<!-- intake: List any older resumes that remain useful component libraries / historical anchors for a
     specific framing (e.g. a particular domain or seniority). Note when each is still worth mining. -->
{{PLACEHOLDER — older anchors that remain valid component libraries; note what each is still good for, and that you do not auto-default to them when a newer named anchor is a closer match}}

---

## Resume-Base Registry & Governance

This is the formal answer to "which base do I start from, what evidence does it carry, and which older resumes should I mine alongside it?" Read it during base selection (Step 5 of the application spec).

### Registry — current bases by role archetype

<!-- intake: This is the core routing table. One row per role archetype you apply to. Fill each column
     from your own resumes:
       - Role archetype: the kind of role (be specific enough to route, e.g. "growth/engagement",
         "0->1 / new products", "B2B platform", "benefits / member experience").
       - Current base: the finished resume you'd start that archetype from (and its file path).
       - Evidence modules it carries: the named bullet packages that base already includes.
       - Older resumes to mine alongside: where stronger role-specific evidence lives that you'd graft in.
     Two example rows are shown as placeholders — replace them and add as many archetypes as you apply to. -->

| Role archetype | Current base (start here) | Evidence modules it carries | Older resumes to mine alongside |
|---|---|---|---|
| **{{PLACEHOLDER — archetype 1, e.g. "0→1 / new products / incubation"}}** | {{PLACEHOLDER — base name + path}} | {{PLACEHOLDER — named modules this base carries}} | {{PLACEHOLDER — older resumes to mine for this archetype}} |
| **{{PLACEHOLDER — archetype 2, e.g. "growth / engagement / retention"}}** | {{PLACEHOLDER — base name + path}} | {{PLACEHOLDER — named modules this base carries}} | {{PLACEHOLDER — older resumes to mine for this archetype}} |

**Copy-don't-rebuild:** each base above is a finalized résumé; for a matching role, **start by copying its file** rather than rebuilding from scratch, then adapt.

### Canonical wording convergence

<!-- intake: If you keep a recurring "core story" section that should read the same across resumes (e.g.
     a current role, a signature project, a consistent product/positioning descriptor), name the
     reference version here so every base copies from one source instead of drifting. Delete this block
     if you don't have a recurring section to keep consistent. -->
{{PLACEHOLDER — if you have a recurring summary or experience section that should stay consistent across resumes, name the canonical reference version to copy from, and list the wording to standardize (tense, key phrases, product descriptor/adjective). Otherwise remove this subsection.}}

### Selected-Writing routing by archetype (optional)

<!-- intake: Fill this only if you attach links to published writing / talks / portfolio pieces and
     want which pieces appear to depend on the role. Pick a "universal lead" piece (used on most
     resumes) plus per-archetype secondary picks. Delete this subsection if you don't attach writing. -->

If you attach selected writing, links, or portfolio pieces, route them by archetype:
- **Universal lead:** {{PLACEHOLDER — the one piece you put on most/all resumes}}
- **{{PLACEHOLDER — archetype}}:** + {{PLACEHOLDER — the secondary pieces for that archetype}}
- **{{PLACEHOLDER — archetype}}:** + {{PLACEHOLDER — the secondary pieces for that archetype}}

Check the dominant flag of the role first when choosing the secondary picks. Still evaluate per role; these are observed defaults, not rules.

### Older evidence-rich resumes — mine for modules, do NOT use wholesale

<!-- intake: List older resumes that use dated framing but still hold your STRONGEST role-specific
     evidence for certain archetypes (e.g. a deep 0->1 story, a platform/permissions story). For each,
     name the specific MODULE worth pulling. Rule: pull the named module, never copy the whole resume;
     always graft onto a current chassis. -->

These may predate your current framing, but they can contain **stronger role-specific evidence** than your newer resumes. Pull the named module; never copy the whole resume. Always graft onto a current chassis.

- **{{PLACEHOLDER — older resume name + path}}** — {{PLACEHOLDER — the specific evidence module worth mining}}
- **{{PLACEHOLDER — older resume name + path}}** — {{PLACEHOLDER — the specific evidence module worth mining}}

The named bullet packages for these modules should live in your experience bank (`04-experience-bank.md`).

### When a completed application becomes a new base (promotion rule)

Promote a finalized application to a **base** only when its **evidence allocation differs materially** across your experience modules **for a distinct role archetype** — not when it merely changes the summary and a few bullets. The test:

> Would a future role of this archetype start meaningfully better from this file than from any existing
> base?

- **Yes →** register it as the base for that archetype in the table above (point at the real file; document its modules and which older resumes to mine alongside).
- **No (same archetype, just re-skinned) →** it's an application, not a base. Leave the archetype's base as-is.

**A single finalized résumé is enough** (copy-don't-rebuild): promotion is **confirmation-only**, never gated on recurrence. The reconcile workflow surfaces base/template candidates (see `learning/source-update-queue.md` → "Base / template candidates"); you confirm, then the exact finalized file is registered here so future similar roles copy it rather than rebuild.

**Detection + notify.** The authoritative version of any resume is the **finalized file** you actually submitted (it reflects your manual edits, which the agent's draft output does not capture). So: when a generated draft's evidence allocation diverges materially from existing bases, the agent should **flag it as a new-base candidate** in the run output. The cleanest confirming signal is a **one-line note from you when you finalize** ("finalized X — make it the base for archetype Y" or "just an application"). Agent-side detection proposes; your one-liner confirms and points at the authoritative file.

### Merge procedure (older evidence + current chassis)

When the strongest evidence for a role lives in an older resume:

1. **Pick the chassis.** Choose the current base for the closest archetype (layout, current summary/positioning wording, factual guardrails, page-two corrections, formatting). This carries current accuracy.
2. **Identify the role archetype**, then pull the **named evidence modules** from the older resume(s) via `04-experience-bank.md`.
3. **Graft** the evidence modules into the chassis — keeping the chassis's current summary section, factual guardrails, formatting, and page two.
4. **Reconcile:** dedupe overlapping bullets, respect space (substitutions not additions), and verify no older factual overreach slipped in (e.g., pre-update wording, named single tools, or stretched claims on a grafted module).

The point of the merge procedure: starting only from your most recent resume can produce an insufficiently targeted result; the strongest version often emerges after grafting the right older evidence module onto a current chassis.

---

## Resume Families (selection map)

<!-- intake: Families are broader groupings than the registry rows above — use them when a role doesn't
     map cleanly to one named base. Define a family per cluster of role types you pursue. The headers
     below are a reusable scaffold: replace the example family names with your own clusters, and fill
     each section from your resume history. Keep only the families relevant to your search. -->

Families group your role types into clusters, each with its likely anchor resumes and framing notes. Use a family when a role doesn't map cleanly to a single named base in the registry above.

### Family template (copy per family)

**Family: {{PLACEHOLDER — family name, e.g. "Growth / Consumer Product"}}**

**Use When**
- {{PLACEHOLDER — the conditions that make this family the right fit}}

**Likely Anchor Resumes**
- {{PLACEHOLDER — your resumes that anchor this family}}

**Key Characteristics**
- {{PLACEHOLDER — what the framing emphasizes for this family}}

**Best For**
- {{PLACEHOLDER — the specific role types this family serves}}

**Page 2 Guidance**
- {{PLACEHOLDER — when to keep the default page 2 vs. swap in a role-specific variant}}

**Format Notes**
- {{PLACEHOLDER — any per-family formatting choices, e.g. flat vs. grouped experience bullets}}

<!-- intake: duplicate the Family template block above for each cluster of roles you apply to
     (e.g. domain-core, domain+growth, platform/workflow, head-of-product/leadership, work tools,
     consumer-core). Delete families that don't apply to you. -->

---

## Special-Purpose Anchors

<!-- intake: Some resumes aren't a full family but are strong starting points for a narrow set of
     roles. List them here with the signals that make each relevant, and which families they can
     reinforce. Delete this section if you don't have any. -->

These are not full resume families, but they are strong starting points for specific types of roles.

### {{PLACEHOLDER — special-purpose anchor name}}
Best used when the role emphasizes:
- {{PLACEHOLDER — the signals that make this anchor relevant}}

Most often relevant within:
- {{PLACEHOLDER — the families this anchor can reinforce}}

---

## Notes on Outliers and Reuse

Not every strong prior resume needs its own full family.

If a resume is highly reusable but only for a narrow set of cases, treat it as:
- a secondary anchor within an existing family, or
- a special-purpose anchor

This keeps the resume index useful and flexible without making it overly complex.

---

## Default Selection Rules

Evaluate the **whole anchor set** — the Primary Named Anchors first, then the family map — and choose the best strategic match for the role; **explain why it is strongest versus the alternatives**. Do not auto-default to any single resume. A base is a starting point, not a mandate to keep its bullets.

If a role clearly maps to one family, use that family's anchor resume as the starting point.

If a role spans multiple families:
- choose the family that best matches the actual hiring priorities
- then borrow emphasis from the secondary family as needed

If unclear:
- prefer the most recent relevant anchor resume
- prefer the resume family that best matches page 1 needs
- keep page 2 stable unless there is a strong reason to change it

---

## Notes

This is a working routing layer for resume selection.

It should be updated over time when:
- a new application creates a clearly stronger anchor
- a new resume family emerges
- an existing family becomes too broad and needs splitting
- an older anchor is no longer the best representative example
