# Materials Inventory  (TEMPLATE)

<!--
  TEMPLATE — copy to `00-INTAKE/materials-inventory.md` (gitignored); /intake maintains the instance.
  This file is the INDEX of every career material you've given intake. It does not store the materials
  themselves — raw content lives as files under 00-INTAKE/01-about-you/ and 02-where-you-want-to-go/,
  or as saved pasted-text files. Append-only: add a row when material arrives; never delete — mark it
  `superseded` or `excluded` instead.

  NOTE: Full inventory behavior (auto-diffing the folders on each /intake run, saving pasted facts as
  timestamped files, etc.) is wired up in a later V2 unit. For now this template establishes the
  structure and the truth firewall.
-->

## The truth firewall (non-negotiable)

A material's **family** decides whether it can become evidence about you:

- `about-you` — evidence about the candidate: resumes, LinkedIn export, brag/wins docs, reviews, metrics.
- `held-role-jd` — a job description for a role the candidate **actually held** (evidence, in an employer's words).
- `voice` — writing samples / portfolio / published work (style + credibility only, never factual claims).
- `where-you-want-to-go` — a target / dream / reaching-for role. **Direction only.** Shapes scoring and lanes; it is **never** treated as proof the candidate has done that work.
- `unclear` — not yet classified. Intake must confirm the family (held vs. reaching-for) before using it.

**Wanting a role never puts its requirements on your resume.** When a JD's family is `unclear`, intake asks before using it.

## Status values

`pending` (received, not yet ingested) · `ingested` · `superseded` (a newer version exists) · `excluded` (intentionally not used) · `needs-review` (intake flagged a question for you)

## Inventory

| ID | Source | Family | Added | Status | Fed into | Notes |
|----|--------|--------|-------|--------|----------|-------|
| <!-- M001 --> | <!-- filename under 01-about-you/, or "pasted-YYYY-MM-DD", or a URL --> | <!-- about-you / held-role-jd / voice / where-you-want-to-go / unclear --> | <!-- YYYY-MM-DD --> | <!-- pending / ingested / superseded / excluded / needs-review --> | <!-- which instance files it informed, or — --> | <!-- recency, contradictions, why superseded, classification rationale --> |

<!-- Append new rows above. IDs are stable cross-references (use them in learning-ledger / source-update-queue notes later). -->
