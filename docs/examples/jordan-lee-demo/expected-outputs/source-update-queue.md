# Source-Update Queue

Proposed edits to canonical generation files, awaiting human review. Produced by the reconcile workflow (`reconcile-spec.md`).

**HARD RULE:** reconcile only **proposes** here. A human applies edits separately, after review. Nothing in this file is auto-applied. This is a maintenance file and is **not** read during a normal résumé-generation run.

## What this is

The review queue for the learning loop. When a reconcile finds a pattern concrete enough to imply a specific edit to a named canonical file (your profile, resume index, experience bank, summary/skills libraries, etc.), it drops a proposal here. Each proposal must clear a gate before a human applies it.

## Gate (when an item becomes review-ready)

Per `reconcile-spec.md` §9, an item graduates from `proposed` to `confirmed-ready-to-apply` only when **at least one** is true:
- you explicitly confirm it, or
- it recurs across **≥2** completed applications.

Even when ready, the actual edit to a canonical file is **always a separate, deliberate human action**. The gate promotes an item to "review me"; it never auto-applies. Single-occurrence items are **not** discarded — they are kept on the watch list and are promotable anytime on your confirmation (`reconcile-spec.md` §9a).

Status legend: `proposed` · `needs-confirmation` · `needs-2nd-occurrence` · `confirmed-ready-to-apply` · `applied` · `rejected`.

---

## Queue

### [needs-confirmation] 04-experience-bank.md — Drop AI bullet tail; relocate boundary language

- **Proposed change:** For the [variant-ai] Tilebridge AI bullet: remove the trailing clause '— a practitioner's use of AI tools, not ML engineering' from the bullet body. Ensure the boundary (practitioner use, not ML engineering) lives instead in the summary or the skills parenthetical, where it reads as positioning rather than a defensive disclaimer.
- **Rationale:** Jordan dropped this tail from the submitted resume. Hypothesis: once the workflow mechanic ('I write the brief and edit; the model drafts') is already present in the bullet, the disclaimer reads as defensive rather than clarifying. Positive-framing language in the bullet is sufficient; boundary language is better placed higher in the document.
- **Confidence:** med — pending Q1 confirmation
- **Evidence:** Thornbury Sr PMM AI Workflows (06-25-26) · **occurrences:** 1
- **Status:** needs-confirmation (promotable now on Jordan's answer to Q1)
- **Source:** `PRIVATE__YOUR_FILES_GITIGNORED/05-SUBMITTED-APPLICATIONS__YOUR_PRIVATE_INFO/2026/Thornbury - Sr PMM AI Workflows - 06-25-26/reconcile-report - Thornbury - Sr PMM AI Workflows - 06-25-26.md`

### [needs-confirmation] 04-experience-bank.md — Add shorter win-loss bullet variant

- **Proposed change:** Add a shorter variant of the win-loss bullet that omits 'the messaging hierarchy' and 'not the roadmap owner', retaining only 'fed themes into roadmap conversations as an input partner.' Label it as the IC-context variant so the agent can select it for roles where scope-reduction language would over-hedge.
- **Rationale:** Jordan removed both the scope-of-influence phrase ('messaging hierarchy') and the negative qualifier ('not the roadmap owner') while keeping 'as an input partner'. The positive framing alone appears sufficient. Separate Q3 (messaging hierarchy) is ambiguous — may be intentional scope reduction or just editorial simplicity.
- **Confidence:** med (Q2 answer strengthens/weakens; Q3 may split this into two changes)
- **Evidence:** Thornbury Sr PMM AI Workflows (06-25-26) · **occurrences:** 1
- **Status:** needs-confirmation (promotable now on Jordan's answers to Q2 and Q3)
- **Source:** `PRIVATE__YOUR_FILES_GITIGNORED/05-SUBMITTED-APPLICATIONS__YOUR_PRIVATE_INFO/2026/Thornbury - Sr PMM AI Workflows - 06-25-26/reconcile-report - Thornbury - Sr PMM AI Workflows - 06-25-26.md`

### [needs-confirmation] 00-job_application_agent.md — IC-only routing rule: suppress people-management bullets

- **Proposed change:** Add a routing rule: when the target role is IC-only (no people-management language in the JD), suppress bullets that mention intern management, mentoring, or freelancer coordination (e.g. the Birchwood intern/people-management bullet). These read as padding and dilute evidence density for IC roles.
- **Rationale:** Jordan removed the Birchwood intern/freelance-coordination bullet despite the agent recommending no changes to Birchwood. The role had no people-management scope. Hypothesis: a single intern-mentoring mention is net-negative for IC-only roles.
- **Confidence:** med — pending Q4 confirmation
- **Evidence:** Thornbury Sr PMM AI Workflows (06-25-26) · **occurrences:** 1
- **Status:** needs-confirmation (promotable now on Jordan's answer to Q4)
- **Source:** `PRIVATE__YOUR_FILES_GITIGNORED/05-SUBMITTED-APPLICATIONS__YOUR_PRIVATE_INFO/2026/Thornbury - Sr PMM AI Workflows - 06-25-26/reconcile-report - Thornbury - Sr PMM AI Workflows - 06-25-26.md`

### [needs-confirmation] 05-summary-quick.md — Register submitted Option 2 text as canonical Family B AI-native closer

- **Proposed change:** Register the submitted Option 2 summary text (as edited by Jordan) as the canonical Family B closer for AI-native company applications. The submitted text is: 'I'm a senior PMM who actually talks to customers every quarter — the win-loss and discovery interviews that keep positioning honest. Across ~8 years in B2B SaaS I've built competitive programs from scratch and led GTM for launches across product, sales, and lifecycle. I adopted AI tools early and use them pragmatically in the GTM workflow. Now I want to bring that to an AI-native company, where keeping claims grounded matters most.'
- **Rationale:** This is the first finalized, submitted summary from Jordan's pipeline. It is a clean, voice-true instance of the AI-native company closer with Jordan's specific edits (added 'pragmatically', removed 'honesty'). Registering it prevents future agents from reverting to the unedited template form.
- **Confidence:** high
- **Evidence:** Thornbury Sr PMM AI Workflows (06-25-26) · **occurrences:** 1
- **Status:** needs-confirmation (high confidence; promotable now; one occurrence is sufficient for a summary registration)
- **Source:** `PRIVATE__YOUR_FILES_GITIGNORED/05-SUBMITTED-APPLICATIONS__YOUR_PRIVATE_INFO/2026/Thornbury - Sr PMM AI Workflows - 06-25-26/reconcile-report - Thornbury - Sr PMM AI Workflows - 06-25-26.md`

---

## Watch list (single-occurrence — durably preserved, NOT moot)

Every item here is preserved indefinitely. Each is promotable now on your confirmation — you do not need to wait for a 2nd occurrence. Nothing here is discarded as "moot" (`reconcile-spec.md` §9a).

### [watch] 06-skills-quick.md — Add routing note: suppress 'Pricing & Packaging (Partner)' when absent from JD

- **Proposed change:** Add a routing note to 'Pricing & Packaging (Partner)' in the skills bank: suppress for roles where P&P is absent from the JD. Do not include proactively.
- **Rationale:** Jordan dropped P&P from the Thornbury submission (11 vs. 12 recommended skills). P&P was not present in the JD. Hypothesis: Jordan applies skills as JD-mirrored, or prefers not to flag P&P ownership ambiguity proactively. One occurrence — cannot distinguish relevance decision from length preference or boundary concern without Q5 answer.
- **Confidence:** low — pending Q5 confirmation
- **Preserved:** yes — promotable now on Jordan's answer to Q5, or auto-surfaced at a 2nd occurrence
- **Evidence:** Thornbury Sr PMM AI Workflows (06-25-26) · **occurrences:** 1
- **Status:** needs-2nd-occurrence (or confirmation via Q5)
- **Source:** `PRIVATE__YOUR_FILES_GITIGNORED/05-SUBMITTED-APPLICATIONS__YOUR_PRIVATE_INFO/2026/Thornbury - Sr PMM AI Workflows - 06-25-26/reconcile-report - Thornbury - Sr PMM AI Workflows - 06-25-26.md`

### [watch] voice — ', internal' qualifier dropped from positioning bullet

- **Proposed change:** No specific file edit yet — this is a pattern observation. Jordan dropped ', internal' from '(directional, internal)' → '(directional)' in the positioning bullet. Consistent with broader pattern of trimming defensive/over-hedged parentheticals (AI bullet tail, roadmap-owner clause). If this recurs, consider a general voice rule: avoid ', internal' qualifiers in bullets; let the qualifier live at the document level if needed.
- **Rationale:** Low signal alone; pattern-consistent with other trims in this application. Insufficient for a specific edit proposal at one occurrence.
- **Confidence:** low
- **Preserved:** yes — promotable on confirmation or 2nd occurrence
- **Evidence:** Thornbury Sr PMM AI Workflows (06-25-26) · **occurrences:** 1
- **Status:** needs-2nd-occurrence (or confirmation)
- **Source:** `PRIVATE__YOUR_FILES_GITIGNORED/05-SUBMITTED-APPLICATIONS__YOUR_PRIVATE_INFO/2026/Thornbury - Sr PMM AI Workflows - 06-25-26/reconcile-report - Thornbury - Sr PMM AI Workflows - 06-25-26.md`

---

## Base / template candidates (copy-don't-rebuild — confirmation-only, NOT subject to ≥2)

Finalized résumés that cleanly represent a role archetype. On your confirmation, register the **exact finalized résumé** as a canonical base in your resume index so future similar roles **copy it rather than rebuild**. One occurrence is enough; this path is never gated on recurrence (`reconcile-spec.md` §9a).

### Thornbury Sr PMM AI Workflows (06-25-26) — AI product marketing + workflow-automation SaaS + anti-hype/grounded-claims culture

- **Archetype:** AI product marketing + workflow-automation SaaS + anti-hype/grounded-claims culture
- **Resume:** `PRIVATE__YOUR_FILES_GITIGNORED/05-SUBMITTED-APPLICATIONS__YOUR_PRIVATE_INFO/2026/Thornbury - Sr PMM AI Workflows - 06-25-26/` (the finalized submitted PDF)
- **Configuration:** Option 2 summary (Jordan's edits), [variant-ai] bullet swap (tail dropped), win-loss bullet trimmed (IC-clean: no negative qualifier, no scope clause), Birchwood intern bullet removed, 11-skill block (P&P dropped)
- **Recommendation:** Future roles at Series B+ AI-native or AI-tooling companies emphasizing honest positioning, customer research, and pragmatic AI fluency should copy this resume as the starting point rather than rebuilding from the base. This is the tightest, most submitted-and-approved configuration of the AI Product Marketing family as of 2026-06-25.
- **Action needed:** Jordan to confirm → promote to resume index as 'Jordan Lee — Sr PMM AI Workflows (Thornbury, 2026)'. Consider confirming after answering Q1–Q5, since a few open edits (AI tail, win-loss variant) could further refine the canonical config.
- **Status:** awaiting confirmation
