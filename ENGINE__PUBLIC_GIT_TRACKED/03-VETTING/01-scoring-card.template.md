# Scoring Card

<!--
  You don't fill this in by hand — `/intake` writes it for you from your resume + a few quick questions.
  Skim it afterward and tweak any line that doesn't sound like you. It's just plain notes on what makes
  a job score high or low FOR YOU. {{PLACEHOLDERS}} mark what intake fills in.

  How scoring works (you never do any math): the system rates every job 0–100 on the four things below,
  then blends them using the weights. The weights add up to 100 — bump one up if it matters more to you
  (chasing mission? raise "Want it." Optimizing for pay/logistics? raise "Practicality.").
-->

---

## 1. Want it — how much this job pulls you   (weight: 35%)

- **Scores high when:** {{the missions, problems, and kinds of work you're genuinely drawn to}}
- **Scores low when:** {{the spaces and kinds of work that leave you flat}}
- **Your extra must-haves / pulls:** {{1–2 personal factors a generic list would miss — e.g. "climate impact", "remote-first culture", "no ad-tech or gambling"}}

---

## 2. Fit — how strong a candidate you'd look to them   (weight: 30%)

- **Scores high when:** {{the role lines up with your real strengths and your level}}
- **Scores low when:** {{it centers skills you don't have, or wants a pedigree you can't signal}}

---

## 3. Culture — how well their style suits you   (weight: 20%)

- **Scores high when:** {{the working cultures and values you do your best work in}}
- **Scores low when:** {{the environments that wear you down}}

---

## 4. Practicality — does it actually fit your life   (weight: 15%)

- **Scores high when:** the pay clears your range and the location/remote setup works for you
- **Scores low when:** it's below your floor, or the office/commute burden isn't worth it
- **Comp:** target ~{{your target}}, floor ~{{your hard floor}}
- **Location:** {{remote / a specific city / hybrid; whether you'll relocate}}
- **Dealbreakers:** {{hard nos}}

<!-- Scorer note: a bare "Location: <City>" line is usually the company HQ, not a relocation requirement.
     Only treat on-site as a burden when the posting actually requires it (and weigh the day count). -->
<!-- The structured comp numbers + location/workstyle preferences ALSO live in jail.config.json (the machine-readable
     source for later candidate-relative ranking/coloring). Intake fills both from the same answers; keep them in sync. -->

---

## Fair-scoring rules — apply to every dimension

<!-- GENERAL scoring protections, identical for every user. Intake copies this block verbatim into the
     generated instance; keep it, and do NOT personalize it with names, companies, or salary numbers. -->

**Use the full 0–100 range.** Don't compress most jobs into a narrow middle. Reserve very low scores for fundamental or multiple central mismatches and very high scores for unusually strong matches. The goal is realistic *differentiation* — never force a batch to contain high scores, and never inflate a weak match.

**Fit — how strong a candidate you'd look to them:**
- Score from EVIDENCE of qualification, **not** from how much the candidate *wants* the role, lane, or mission. Being outside a preferred lane is not a weaker fit.
- Distinguish evidence strength: direct · transferable · light · absent · unknown. Give real credit for strong **transferable** evidence.
- **Omission ≠ absence:** a summary profile that doesn't mention something is not proof the candidate lacks it — treat a requirement with no signal as *unknown*, not *failed*.
- **Count one gap once** — don't deduct the same underlying gap across several sub-factors; let the weakest *central* requirement set the ceiling.
- **Imperfect ≠ implausible.** A missing nice-to-have costs a few points, not twenty.
- **Day-one gate vs. learnable:** if the posting says an area isn't required or can be grown into, don't score it as a hard gate.
- **AI is not binary:** distinguish (1) AI-tool fluency · (2) hands-on AI building · (3) production-scale deployment · (4) model/infra ownership · (5) mature eval-system operation. Wanting (1)–(2) is a fair-to-strong fit for a hands-on builder; only years of (3)–(5) required at day one should pull a candidate without them materially down.
- **Education:** "a degree" or "business/product degree accepted" is satisfied by a business degree; "CS preferred" is a modest concern at most; only "CS required" / "former-engineer / regular production coding" is a material gate. A missing CS degree is not a universal PM weakness.

**Culture — how well their style suits you:**
- A job posting is thin evidence of real culture. When it reveals little, **score neutrally and treat confidence as low** — don't manufacture a vibe from generic corporate adjectives, don't assume published values equal lived culture, and don't infer manager quality with no manager evidence.
- Grind language ("fast-paced," "ambitious," "high performance") is not automatically negative — score down only for relentless hustle, normalized overwork, aggression, or contempt for boundaries.
- **Mission ≠ culture:** don't reward Culture just because the candidate likes the mission (that's "Want it"), and don't let mission or culture move the Fit score.

**Practicality:** low comp is a **penalty, not a veto** — reflect the hit, but don't disqualify a strong opportunity on comp alone. Skill/qualification gaps belong in Fit, never here.
