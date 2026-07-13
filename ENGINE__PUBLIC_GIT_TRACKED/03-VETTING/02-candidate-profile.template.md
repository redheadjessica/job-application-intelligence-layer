# {{FULL_NAME}} — Scoring Profile

<!--
  TEMPLATE — the /intake skill fills this in from your resume + a few questions, then writes
  the finished copy to:  PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/02-candidate-profile.md  (which is what the engine reads,
  alongside 01-scoring-card.md).

  This file tells the scorer WHO you are, so it can judge Market Perception and Company Style
  and sort jobs into your lanes. Keep it tight — it's read in full on every job.
  {{PLACEHOLDERS}} and <!-- intake: ... --> comments mark what to fill.
-->

Use this file when assessing Market Perception and Company Style scores, and to assign each job a lane.

---

## Background
<!-- intake: 2–4 sentences. Who they are professionally, the anchor credential(s) a recruiter would notice,
     the domains they've worked in, and the kind of operator they are. Pull from the resume; confirm the framing. -->

{{2–4 sentence professional summary — seniority, anchor experience, domains, operating style}}

---

## Skill Strengths (score higher when a role emphasizes these)
<!-- intake: bullet the skill clusters that are a clear YES. Derive from the resume, then confirm/trim. -->

- {{strength 1}}
- {{strength 2}}
- {{strength 3}}
- {{... 6–11 bullets total}}

---

## Skill Gaps (score lower when a role centers these)
<!-- intake: the things that, when CENTRAL to a role, make the user a weaker or mis-cast fit.
     Not weaknesses to hide — signals for triage. Ask: "what kind of role is NOT for you?" -->

- {{gap / anti-fit 1}}
- {{gap / anti-fit 2}}
- {{... 3–6 bullets}}

---

## Seniority Context
<!-- intake: 2–4 sentences on level. Where they'd look over-leveled, where under-leveled, and the sweet spot. -->

{{level framing — e.g. "Senior-to-staff IC product leader. Over-leveled for mid-level PM roles; under-leveled for roles managing 4+ PMs. Player-coach / IC-heavy senior roles are the sweet spot."}}

---

## Priority Lanes
<!-- intake: 2–5 named lanes, most-wanted first. The scorer's Lane Fit maps each job to the closest lane (or "Outside lanes");
     the matched lane's priority drives the spreadsheet's Lane stoplight coloring (p1 green / p2+ amber / Outside red) AND
     these are the shared lane taxonomy — the id/name/priority of each lane is mirrored in jail.config.json. (Note: "Lane" in
     the spreadsheet is the job's own category; "Lane Fit" is this candidate-relative mapping.) Derive candidates from the
     user's domains + reaching-for roles; confirm order.
     TRUTH FIREWALL: lanes come partly from roles the candidate WANTS — they set direction and scoring, never proof
     of experience. Copy one block per lane; keep ids stable (jail.config.json mirrors them). -->

### Lane 1 — {{name}}  ·  priority: 1  ·  id: {{kebab-id}}
- **Target titles:** {{titles}}
- **Target industries / company types:** {{...}}
- **Fits:** {{the role shape / scope / stage that's a strong match}}
- **Does not fit:** {{the role shape that isn't this lane}}
- **Preferred resume base:** {{base, or "TBD"}}
- **Summary / skills emphasis:** {{what to lead with for this lane}}
- **Notes / tradeoffs:** {{anything to remember}}

### Lane 2 — {{name}}  ·  priority: 2  ·  id: {{kebab-id}}
{{same fields — copy the block above}}

<!-- Add more lanes as needed (2-4 distinct lanes beat 6 thin ones). -->
<!-- Lane id mirror for jail.config.json: [{ "id": "...", "name": "...", "priority": 1 }, ...] -->

---

## Practical Constraints
<!-- intake: the hard, scalar facts the scorer needs for Practicality. Ask directly; these are easy questions. -->

- **Comp:** target ~{{target base}}; soft floor ~{{floor base}} (penalize clearly-below when comp is known). {{any exception conditions}}
- **Location:** {{home base + arrangement — e.g. "Remote ideal; open to hybrid in <city>; will not relocate to <X>"}}
- **Dealbreakers:** {{hard nos — e.g. "no on-site 4+ days; no <industries>; no <role types>"}}
- **Other:** {{anything else that should hard-gate or strongly tilt practicality}}
