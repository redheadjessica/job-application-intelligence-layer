# Skills Reconciliation Rules

## Purpose
This process governs how new skills are merged into your canonical skills library (`06a-skills-library.md`). It is reusable process discipline — it does not contain any candidate's data, only the rules for *how* skill edits get evaluated.

## Core Principle
The canonical skills library prioritizes:
- credibility
- clarity
- reusability
- stable categorization over comprehensiveness.

Not every extracted skill belongs in the canonical library.

## Decision Rules for New Skill Candidates

### Add a skill to the canonical library only if:
- it reflects a real, defensible capability
- it is likely to be reused across multiple applications
- it adds meaningful new signal not already covered by an existing canonical skill
- it can be placed clearly into one of these confidence / placement tiers:
  - Resume-Safe
  - Selective
  - Collaborative
  - Conversation-Level
  - Excluded / Do Not Overclaim

<!-- intake: the five tiers above are the standard placement model used by 06a-skills-library.md.
     If you rename or restructure those tiers, keep this list in sync. -->

### Do not add a skill if:
- it is just a synonym of an existing skill
- it is a fragmented parsing artifact
- it is too generic to strengthen positioning
- it is legacy, outdated, or low-signal
- it is a one-off phrase tied to a single resume experiment
- it creates overclaim risk

## Required Actions for Each New Candidate
For each new skill candidate:
1. Check whether it is already covered conceptually by an existing canonical skill.
2. If yes, add it to the synonyms map (in `06-skills-quick.md`) instead of the main library.
3. If no, classify it into the correct confidence / placement section.
4. Record the source of the skill:
   - resume-derived
   - direct calibration
   - new experience
   - role-specific positioning
5. Record whether it was:
   - added
   - mapped as synonym
   - rejected
   - deferred for human review

## Update Discipline
- The canonical library should remain stable and intentionally edited.
- Bulk extracted skills should always be reviewed through these rules first.
- Prefer recording a candidate (and its disposition) over silently mutating the canonical file unless explicitly instructed to modify the canonical library.
