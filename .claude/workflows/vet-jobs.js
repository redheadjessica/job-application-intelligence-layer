export const meta = {
  name: 'vet-jobs',
  description: 'Score a dated batch folder of job descriptions in parallel (one agent per job), then assemble CSV + Markdown rankings into that same folder',
  whenToUse: 'Run a job-vetting batch fast. Pass the batch folder path as args, e.g. {folder: "__READY_TO_REVIEW__PRIVATE_GITIGNORED/06-02-26"}.',
  phases: [
    { title: 'Discover', detail: 'list job files in the batch folder', model: 'haiku' },
    { title: 'Score', detail: 'one agent per job, scored concurrently', model: 'sonnet' },
    { title: 'Assemble', detail: 'write CSV + Markdown, then build the formatted XLSX', model: 'haiku' },
  ],
}

// ---- Inputs ----
// Named-workflow invocation can deliver `args` as a JSON string; parse it back to a value first.
let A = args
if (typeof A === 'string') { try { A = JSON.parse(A) } catch (_) { /* leave as raw string */ } }
const FOLDER = (A && typeof A === 'object' && A.folder) ? A.folder : A
if (!FOLDER || typeof FOLDER !== 'string') {
  throw new Error('Pass the batch folder path as args, e.g. {folder: "__READY_TO_REVIEW__PRIVATE_GITIGNORED/06-02-26"} or just "__READY_TO_REVIEW__PRIVATE_GITIGNORED/04-09-26".')
}
// Optional: write the rankings somewhere OTHER than the scored folder (e.g. a sibling
// "1 - Rankings/" tier), and name them after the batch rather than the source subfolder.
const OUT_DIR = (A && typeof A === 'object' && A.outDir) ? A.outDir : null
const BATCH_NAME = (A && typeof A === 'object' && A.batchName) ? A.batchName : null

// Rubric + profile are the candidate's private instances under PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/.
const RUBRIC = 'PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/01-scoring-card.md'
const PROFILE = 'PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/02-candidate-profile.md'

// ---- Schemas ----
const DISCOVER_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['root', 'jobs'],
  properties: {
    root: { type: 'string', description: 'Absolute path of the batch folder' },
    jobs: {
      type: 'array',
      description: 'One entry per distinct job, deduped (.txt/.md preferred over .pdf for the same job)',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['file', 'abs_path'],
        properties: {
          file: { type: 'string', description: 'Filename only, e.g. senior-pm-acme.txt' },
          abs_path: { type: 'string', description: 'Absolute path to read' },
        },
      },
    },
    quarantined: { type: 'integer', description: 'count of thin/failed posts prep quarantined and NOT ranked (sibling "Needs Review/" + "Failed/" file counts, or 0 - Prep Report/prep-manifest.json counts.thin+counts.failed); 0 if none' },
  },
}

// NOTE (schema kept deliberately terse): the platform runs a safety classifier over the output
// schema, and it rejects overly large schemas ("output schema too large to classify safely").
// Every scoring rule that used to live in these field descriptions is stated in full in the
// scoring PROMPT below (the "Scoring rules" bullets) — that's the real instruction source. Keep
// these descriptions short one-liners; put any new detailed guidance in the prompt, not here.
const SCORE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: [
    'content_verified', 'content_issue',
    'company', 'title_and_link', 'location', 'comp_range', 'lane', 'lane_fit',
    'desire_score', 'market_perception_score', 'company_style_score', 'practicality_score',
    'comp_lifestyle_fit_notes',
    'mission_fit_notes', 'scope_fit_notes', 'top_reasons', 'top_concerns',
  ],
  properties: {
    content_verified: { type: 'boolean' },
    content_issue: { type: ['string', 'null'] },
    company: { type: 'string' },
    title_and_link: { type: 'string' },
    location: { type: 'string' },
    comp_range: { type: 'string' },
    lane: { type: 'string' },
    lane_fit: {
      type: 'object', additionalProperties: false,
      required: ['primary_lane', 'secondary_lane', 'confidence', 'note'],
      properties: {
        primary_lane: { type: 'string' },
        secondary_lane: { type: ['string', 'null'] },
        confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
        note: { type: 'string' },
      },
    },
    desire_score: { type: 'integer', minimum: 0, maximum: 100 },
    market_perception_score: { type: 'integer', minimum: 0, maximum: 100 },
    company_style_score: { type: 'integer', minimum: 0, maximum: 100 },
    practicality_score: { type: 'integer', minimum: 0, maximum: 100 },
    comp_lifestyle_fit_notes: { type: 'string' },
    mission_fit_notes: { type: 'string' },
    scope_fit_notes: { type: 'string' },
    top_reasons: { type: 'string' },
    top_concerns: { type: 'string' },
  },
}

// ---- Phase 1: discover job files ----
phase('Discover')
const discovery = await agent(
  `List the job-description files in this batch folder: "${FOLDER}" (relative to the project root, or it may already be absolute).

Steps:
1. Resolve the folder to an absolute path and run an "ls" of it.
2. Job files end in .txt, .md, or .pdf.
3. EXCLUDE any output/config files: anything ending in "-rankings.csv" or "-rankings.md", the URL list (job_urls.txt or "Submitted URLs*"), and anything named like a rubric/header/agent file (*scoring-card*, *candidate-profile*, csv-header*, *vetting_agent*).
4. Dedupe: if two files clearly represent the SAME job (same filename stem, differing only by extension), keep only one and prefer .txt, then .md, then .pdf.
5. Return the absolute folder path as "root" and one entry per distinct job.
6. Quarantine count: if a sibling "Needs Review/" and/or "Failed/" folder exists next to this source folder (under "3 - Source Material/"), OR a "0 - Prep Report/prep-manifest.json" exists in the batch, return the number of thin+failed (quarantined) posts as "quarantined" (count the files in those two folders, or read counts.thin+counts.failed from the manifest). Return 0 if none.`,
  { phase: 'Discover', model: 'haiku', schema: DISCOVER_SCHEMA, label: 'discover files' }
)

if (!discovery || !discovery.jobs || discovery.jobs.length === 0) {
  return { error: `No job files found in "${FOLDER}".`, folder: FOLDER }
}
log(`Found ${discovery.jobs.length} jobs in ${discovery.root} — scoring in parallel`)

// Load rubric + profile ONCE and inline them into every scoring prompt, instead of
// having all N scoring agents each re-read the same two files (N x 2 redundant reads).
const DIMENSIONS_FILE = 'ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/score-dimensions.json'
const REFS_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['rubric', 'profile', 'weights'],
  properties: {
    rubric: { type: 'string' },
    profile: { type: 'string' },
    config: { type: 'string', description: 'Full raw contents of jail.config.json (structured candidate preferences), or "" if the file does not exist' },
    dimensions: { type: 'string', description: `Full raw JSON text of ${DIMENSIONS_FILE} (engine-owned default score labels/weights/definitions), or "" if it cannot be read` },
    weights: {
      type: 'object', additionalProperties: false,
      required: ['desire', 'market', 'style', 'practicality'],
      description: 'The four dimension weights as PERCENTAGES parsed from the scoring card section headers, in order (1st->desire, 2nd->market, 3rd->style, 4th->practicality). Return 0 for all four if the card does not state weights.',
      properties: {
        desire: { type: 'number' }, market: { type: 'number' },
        style: { type: 'number' }, practicality: { type: 'number' },
      },
    },
  },
}
const refs = await agent(
  `Read these files and return their FULL text verbatim (do not summarize or truncate):
- ${RUBRIC}  -> field "rubric"
- ${PROFILE} -> field "profile"
- jail.config.json -> field "config" (the candidate's structured preferences; if the file does not exist, return "" for config)
- ${DIMENSIONS_FILE} -> field "dimensions" (engine-owned default score labels/weights/definitions; if it cannot be read, return "" for dimensions)

Also extract the FOUR dimension weights from the scoring card's section headers, which look like "(weight: NN%)". Return them as raw percentages in "weights", in the order the dimensions appear: 1st -> weights.desire, 2nd -> weights.market, 3rd -> weights.style, 4th -> weights.practicality (e.g. 35, 30, 20, 15). If the card does not clearly state weights, return 0 for all four.`,
  { phase: 'Discover', model: 'haiku', schema: REFS_SCHEMA, label: 'load rubric+profile+dimensions' }
)

// ---- Resolve score-column labels + definitions from the engine's shared metadata file ----
// score-dimensions.json is the single default owner (see that file's _README). This literal object
// is a DEFENSIVE FALLBACK only, kept in sync with it, used if the file can't be read at runtime.
const FALLBACK_DIMS = {
  order: ['final', 'market', 'desire', 'style', 'practicality'],
  final: { label: 'FINAL Weighted Score' },
  desire: { label: 'Your Desire Score', schema_key: 'desire_score', default_weight: 35,
    definition: "Estimates how much you'd likely want the role if hired and if logistics were workable. May consider mission, product, users, problems, scope, career direction, and personal interests. Should not primarily measure compensation, location, or whether the employer is likely to hire you." },
  market: { label: 'How They May See Your Profile', schema_key: 'market_perception_score', default_weight: 30,
    definition: 'Estimates how competitive and legible you may appear to this employer before tailoring, based on the canonical summary profile available during vetting and the job posting. It does not use the newly tailored resume. A preference for the company, mission, or lane is not evidence that the employer will see you as qualified.' },
  style: { label: 'Culture Fit Score', schema_key: 'company_style_score', default_weight: 20,
    definition: "Estimates how well the company's apparent working style, values, product culture, and environment may suit you, based on the evidence actually available. Job postings provide incomplete culture evidence. When little reliable information is available, this score should remain closer to neutral and should be treated as lower-confidence." },
  practicality: { label: 'Comp + Lifestyle Fit Score', schema_key: 'practicality_score', default_weight: 15,
    definition: "Estimates how well compensation, location, work arrangement, travel, schedule, and other practical considerations fit your stated preferences. A lower score reduces the opportunity's priority but is not automatically a veto." },
}
let DIMS = FALLBACK_DIMS
try {
  if (refs && refs.dimensions && refs.dimensions.trim()) {
    const parsed = JSON.parse(refs.dimensions)
    if (parsed && parsed.final && parsed.desire && parsed.market && parsed.style && parsed.practicality) DIMS = parsed
  }
} catch (_) { /* keep FALLBACK_DIMS */ }
const LABELS = {
  final: DIMS.final.label, desire: DIMS.desire.label, market: DIMS.market.label,
  style: DIMS.style.label, practicality: DIMS.practicality.label,
}
// Required-file guard (V2 template/instance split): the rubric + profile are GENERATED
// instances produced by /intake, not tracked templates. If they're missing/empty, stop with
// an actionable message rather than scoring against nothing.
const haveRefs = !!(refs && refs.rubric && refs.profile)
if (!haveRefs) {
  return {
    error: "I can't vet yet — your scoring card and candidate profile haven't been generated. They're created when you run /intake. Run /intake first to produce PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/01-scoring-card.md and PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/02-candidate-profile.md, then re-run this batch.",
    missing: [RUBRIC, PROFILE].filter((p, i) => !(i === 0 ? (refs && refs.rubric) : (refs && refs.profile))),
  }
}
const prefsBlock = (refs && refs.config && refs.config.trim())
  ? `

<preferences>
${refs.config}
</preferences>`
  : `

<preferences>none generated yet — score comp/location from the profile prose; never invent numbers</preferences>`
const refsBlock = `Use this rubric, profile, and preferences (already loaded — do NOT open any other files for these):

<scoring-card>
${refs.rubric}
</scoring-card>

<profile>
${refs.profile}
</profile>${prefsBlock}`

// Parse the structured config once — used to write the candidate-relative Comp Fit
// LABEL into the CSV. Working Location COLORS are not label-driven: they come
// from norm_contracts.working_location_color() (the canonical 4-hex mapper) inside make_rankings_xlsx.py.
let CFG = {}
try { CFG = (refs && refs.config && refs.config.trim()) ? JSON.parse(refs.config) : {} } catch (_) { CFG = {} }

// ---- First-run completeness nudge ----
// Comp Fit / Lane coloring falls back to neutral/grey when these are missing —
// silently, unless someone happens to open the xlsx and notice the Instructions-tab comment. Flag
// it loudly up front instead, especially useful for a brand-new user's very first batch.
{
  const comp = (CFG && CFG.comp) || {}
  const locArr = (CFG && CFG.location && CFG.location.arrangements) || {}
  const hasComp = comp.floor_base != null || comp.target_base != null
  const hasLoc = Object.values(locArr).some((v) => v != null)
  const hasLanes = Array.isArray(CFG && CFG.lanes) && CFG.lanes.length > 0
  if (!hasComp || !hasLoc || !hasLanes) {
    const missing = [!hasComp && 'comp target/floor', !hasLoc && 'location arrangement ratings', !hasLanes && 'lanes'].filter(Boolean).join(', ')
    log(`⚠ jail.config.json is missing: ${missing}. Comp Fit / Lane coloring will be neutral, and Working Location coloring cannot recognize your home metro, until this is filled in — run /intake (or its update mode) to complete it.`)
  }
}

// ---- Phase 2: score each job concurrently ----
phase('Score')
const scored = await parallel(discovery.jobs.map((job) => async () => {
  const result = await agent(
    `You are scoring ONE job for the candidate's vetting system.

${refsBlock}

Now read ONLY this job description file and score it:
${job.abs_path}

⚠️ HARD STOP — do this FIRST, before any scoring: confirm the file actually contains a real
job posting body (responsibilities, qualifications, role description — actual prose about the
job). Fetches sometimes fail silently and capture something else entirely — website navigation
chrome, a login/apply shell, or (seen in production) hundreds of KB of a JS-rendered page's
theme/config JSON with zero real posting text. Length is NOT a proxy for real content — a huge
file can still be 100% boilerplate. Set content_verified=false and describe the problem in
content_issue if you cannot find genuine posting content, even if the file is large. If
content_verified is true, set content_issue to null and proceed normally.

Scoring rules:
- Four scores, each an INTEGER 0-100: desire_score, market_perception_score, company_style_score, practicality_score.
  - desire_score: how much the candidate would want this role — mission fit, role excitement, domain alignment, personal pull. Compute the scoring card's five Desire sub-factors, THEN apply the card's "⭐ Strategic Career Leverage" rule: a bounded uplift (None/Some/Strong/Exceptional) for a role whose actual mandate would build the specific missing evidence named in the candidate profile's "Target Career Direction / Primary Strategic Gaps / High-Leverage Bridge Work" fields — all three of the card's tests (named-gap, ownership, future-legibility) must hold, it's capped at 85, it can't rescue disliked work, and it NEVER touches Profile/Style/Practicality. If the profile has no target-direction/gaps fields, apply no leverage. When it materially moves the score, note it in one clause of mission_fit_notes (the `Your Desire Score Notes` column) — naming the level and the evidence in that same clause.
  - market_perception_score: how strong a candidate they would appear to this employer — experience match, credibility, likely recruiter reaction.
  - company_style_score: how well the company culture, stage, and working style fit the candidate.
  - practicality_score: how livable/practical the job is — comp relative to the candidate's targets, location/remote fit, logistics, quality of life. Use the <preferences> block (comp target/floor, location arrangement ratings) when present to sharpen this; if preferences are absent, fall back to the profile prose. Preferences inform — they do not override the full rubric/profile.
- Do NOT compute the final score or status — that is handled downstream. Just return the four sub-scores and the fields below.
- Be decisive. Don't over-index on title. Reflect comp/location tradeoffs in practicality_score, not by skipping.
- comp_range: the OUTER ENVELOPE of the APPLICABLE base-salary bands — min(applicable lows)-max(applicable highs), in whole thousands, no $ or commas (e.g. 190-210, or 125-250 where the endpoints come from DIFFERENT bands); "??" if unknown. A band is APPLICABLE when it covers a way the candidate could genuinely take the job: their remote state, an acceptable home-metro office, or a configured relocation option; when the posting shows multiple geo bands and the applicable one can't be resolved, include them all; when multiple levels are genuinely unresolved (the posting might hire at either), include both. EXCLUDE: the candidate's own expectations (never employer data); bands for locations the candidate can't take; bands for unrelated roles listed on the same page; clearly inapplicable levels; and bonus/commission/equity/OTE figures — base salary only. Never output a midpoint, the first tier shown, the first city's band, or one model-picked band when several apply. **AUTHORITATIVE SOURCE: prep writes a "COMPENSATION" section near the top of the file (before "--- JOB TEXT START ---") with a "Base Salary:" bullet list (one bullet per geo/level band, full dollar amounts), an "Additional Compensation:" line, and a "Benefits:" line. When Base Salary lists real dollar bands, treat those bullets as ground truth — apply the applicability filter above to THOSE bands and take the envelope; do not second-guess them from body prose. When Base Salary reads "Employer Did Not Mention Compensation." the employer genuinely didn't publish comp → "??". When it reads "Could Not Verify." or "Conflicting Employer Information: …", use "??" and note the uncertainty in top_concerns. "Additional Compensation" (bonus/commission/equity) is never part of comp_range.** (norm_contracts.py mechanically enforces the N-N format after scoring; the applicability judgment is yours.)
- location: output ONLY the canonical Working Location grammar — exactly one of: "Remote" · "Remote (<detail>)" (e.g. "Remote (states: NY, CA)" when remote is restricted to specific US states) · "Remote or IRL <cities> - <cadence>" · "IRL <cities> - <cadence>" · "Unknown". Every known non-remote location MUST carry the literal "IRL " prefix — NEVER bare "Hybrid", "Onsite", "NYC/SF - 3 days", or "New York hybrid". <cadence> is "N days" for an exact required day count; "N+ days" when the posting states an OPEN-ENDED minimum ("3+ days", "at least 3 days", "a minimum of 3 days") — preserve the open-endedness, "3 days" and "3+ days" are DIFFERENT values; or "unknown days" when the city is known but the day count is not. Use the "Remote or IRL <cities> - <cadence>" form ONLY when remote is genuinely available to the applicant AND an office option also exists — never infer remote from "flexible", "distributed", or "remote-friendly". Abbreviate major cities to their common short form (NYC, SF, LA, DC — only when unambiguous). If the posting names MULTIPLE genuinely-available office cities, keep them ALL, joined with "/" in the candidate's city_priority order from <preferences> (priority cities first, in that order; any other named cities after, in the posting's own order) — e.g. "IRL NYC/SF/Austin - 3 days"; never collapse a multi-office list to one city. "Onsite <city>" means "IRL <city> - 5 days" ONLY when full-time attendance is explicitly established; otherwise "IRL <city> - unknown days". If a city/office location is named ANYWHERE in the posting but the arrangement or day count isn't stated, still output "IRL <City> - unknown days" — a named city is real signal; do NOT collapse it to bare "Unknown". "Unknown" ONLY when the posting gives no location signal at all. A location requirement stated in an APPLICATION QUESTION (e.g. "can you attend the office at least 2 days per week?") counts exactly like one stated in the JD and normalizes the same way. **AUTHORITATIVE SOURCE: prep writes a "WORK DETAILS" section near the top of the file (before "--- JOB TEXT START ---") with "Work Arrangement:", "Working Location(s):" and "Office Expectation:" lines — the fetcher's own structured fields. "Working Location(s)" may list MULTIPLE employer office metros (e.g. "Austin, TX; San Francisco Bay Area; New York City; Washington, D.C.") and "Office Expectation" carries the exact cadence (e.g. "At Least 2 Days Per Week" or "3 Days Per Week, Tuesday–Thursday"). Treat those lines as authoritative ground truth for the employer's eligible cities + day-count; don't second-guess them from body text. Their honest-distinction values mean exactly what they say: "Employer Did Not Mention Working Location." → the employer published no location; "Could Not Verify." → the capture failed (read the body prose as fallback and note the uncertainty); "Conflicting Employer Information: …" → two sources disagree (both readings shown — reflect the uncertainty); "Not Specified" (Office Expectation) → no cadence was stated, never invent one. Then express the result in the canonical grammar above (an "At Least 2 Days Per Week" expectation is open-ended → "2+ days").** For a bare "Location: <City>" line found INSIDE the job description body (not the structured WORK DETAILS section), treat it as the company HQ, not a relocation requirement, unless the posting actually requires on-site presence. (A mechanical normalizer, ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/norm_contracts.py, re-validates this value after scoring — emit exactly the grammar above so nothing needs repair.)
- title_and_link: "Role Title | URL" if a URL is present, else just the title.
- lane: the job's category as "<Bucket> - <Descriptor>", in the job's OWN terms — NOT mapped to the candidate's lanes. Bucket = closest fit from Health / Consumer / Work / Other (exactly "Work", NEVER "Work Tools"; add a new bucket only if truly none fit — keep this set small and reusable). Descriptor = a short 1-2 word phrase, e.g. "Health - DTC Supplements", "Health - Provider Tools", "Health - Consumer Wellness", "Consumer - Home Sharing", "Work - Collaboration", "Work - Productivity", "Work - Project Management", "Work - Legal", "Work - Consumer Research", "Other - Fintech". Reuse an existing descriptor for the same kind of job rather than inventing near-duplicate wording — consistency across jobs matters more than precision on any one job. Mental/behavioral health jobs MUST use the exact string "Health - Mental Health" — no extra qualifier words appended.
- lane_fit: how that job-lane maps to the CANDIDATE's priority lanes — candidate-relative and honest. { primary_lane: EXACTLY one of the candidate's priority-lane names (verbatim from the profile), or "Outside lanes" if it fits none; secondary_lane (or null); confidence ("high"/"medium"/"low"); note (one short phrase) }. If the role is not one of the candidate's lanes, primary_lane = "Outside lanes" (even when the domain sounds related). Do NOT inflate — it is surfaced for the candidate, not added to the score.
- comp_lifestyle_fit_notes: the RATIONALE BREAKDOWN behind practicality_score — the prose companion to that score, exactly like mission_fit_notes is to the mission judgment. Terse pipe-separated parts in the order cash | location | equity+bonus+benefits, each naming the sub-points it earned and the one-phrase reason, e.g. \`Cash 26/40 (midpoint ~$188K) | Location 30/30 (fully remote) | Equity+bonus+401k 19/20 (equity stated; bonus stated; 401k stated)\`. Use whatever sub-factor names and point totals the candidate's scoring card actually defines for this dimension; if the card defines no sub-factors, write the same three-part breakdown in plain phrases without point math. This is the ONLY field where that breakdown belongs. Two columns it must NEVER be written into: **comp_range** stays the mechanical \`N-N\` (or \`??\`) value described above — never prose, never a note; and the **Comp Fit** column is MACHINE-DERIVED downstream from the normalized comp range by norm_contracts.comp_fit_label() — you do not produce it at all, and anything prose-like aimed at it is destroyed on the next normalization pass.
- mission_fit_notes / scope_fit_notes: ONE plain-English sentence each, written the way you'd say it out loud — no sub-factor math, no "=", "/", or "+" notation, no "Mission 27/30 + Role 16/30..." breakdowns. They land in the `Your Desire Score Notes` and `Profile Score Notes` columns. Keep the reasoning in that one sentence; there is no separate detail field.
- top_reasons / top_concerns: semicolon-separated phrases, concise and concrete.
- If PDF extraction is imperfect, make a best effort and note it in scope_fit_notes; do not fail.`,
    { phase: 'Score', model: 'sonnet', schema: SCORE_SCHEMA, label: job.file }
  )
  if (!result) return null
  return { ...result, job_file: job.file, abs_path: job.abs_path }
}))

const rows = scored.filter(Boolean)
if (rows.length === 0) {
  return { error: 'All scoring agents returned empty.', folder: discovery.root }
}

// ---- Resolve dimension weights from the scoring card (fall back to 35/30/20/15) ----
// The card states each dimension's weight as "(weight: NN%)"; the loader returns them above.
// Use them when all four are positive numbers; otherwise use the default. Normalize to fractions
// summing to 1 so the final score stays on a 0-100 scale regardless of how the percentages add up.
const DEFAULT_WEIGHTS = { desire: 35, market: 30, style: 20, practicality: 15 }
function resolveWeights(w) {
  const keys = ['desire', 'market', 'style', 'practicality']
  const ok = w && keys.every((k) => typeof w[k] === 'number' && w[k] > 0)
  const raw = ok ? w : DEFAULT_WEIGHTS
  const sum = keys.reduce((s, k) => s + raw[k], 0) || 100
  const f = {}
  for (const k of keys) f[k] = raw[k] / sum
  return f
}
const W = resolveWeights(refs && refs.weights)
log(`Weights — desire ${Math.round(W.desire * 100)} / market ${Math.round(W.market * 100)} / style ${Math.round(W.style * 100)} / practicality ${Math.round(W.practicality * 100)}`)

// ---- Candidate-relative fit LABELS (ported from make_rankings_xlsx.py — keep in sync) ----
// JS is the single source of this math; the .py maps these label strings -> colors only.
// MIDPOINT rule (approved 2026-07-29, replacing the old high-endpoint-only rule that painted a
// below-floor-midpoint band green): red iff max < floor; green iff midpoint >= target; else yellow.
// norm_contracts.py `comp_fit_label` is the CANONICAL source of this logic — the post-scoring CLI
// pass re-derives the Comp Fit column from the normalized Comp Range and its output wins; this JS
// copy is only the initial fallback value written into the CSV. Keep the two in sync.
function compFitLabel(text, cfg) {
  const t = (text || '').trim()
  const m = t.match(/^(\d+)-(\d+)$/) || (/^\d+$/.test(t) ? [t, t, t] : null)
  if (!t || t.includes('?') || !m) return 'Unknown'
  const comp = (cfg && cfg.comp) || {}
  const floor = comp.floor_base, target = comp.target_base
  if (floor == null && target == null) return 'No comp prefs'
  const lo = Number(m[1]), hi = Number(m[2])
  if (floor != null && hi < floor) return 'Below floor'
  if (target != null) return (lo + hi) / 2 >= target ? 'Meets/above target' : 'Near target'
  return 'Above floor'
}
// `Location Fit` was removed from the contract (2026-07-30): it restated what the canonical
// `Working Location` grammar already encodes, shared its exact 4-hex fill, and was one more derived
// label to keep in sync. Its labeler is gone with it — do not reintroduce one.

// The literal placeholder for an unverified ATS date. Never blank
// (a blank cell reads as "nobody looked"), never the JAIL capture date, never inferred from a URL,
// job id, or search-result age. norm_contracts replaces it only with a date the capture carries.
const UNKNOWN_POSTED_DATE = 'Unknown'

// ---- Per-job DATA COMPLETENESS (comp + working-location capture quality) ----
// Surfaces, per row, whether the score was computed against complete comp/location data — so the
// candidate can tell at a glance which rows to trust without spot-checking. Prefer prep's per-field
// capture status (from the manifest); fall back deterministically to the row's own comp/location text
// for older batches fetched before prep recorded field_status. NOTE: the label wording here is the
// single source; make_rankings_xlsx.py maps the label TEXT -> a color (green/amber/red) and derives
// the same fallback when a CSV predates this column, so keep the vocabulary ("complete" / "not
// verified" / "unknown" / "not posted") stable across both files.
function completenessLabel(compCat, locCat) {
  if (compCat === 'found' && locCat === 'found') return '✓ complete'
  const attn = [], benign = []
  if (compCat === 'unknown') attn.push('comp')
  else if (compCat === 'not_posted') benign.push('comp')
  if (locCat === 'unknown') attn.push('location')
  else if (locCat === 'not_posted') benign.push('location')
  const parts = []
  if (attn.length === 2) parts.push('⚠ comp+location not verified')
  else if (attn.length === 1) parts.push(attn[0] === 'comp' ? '⚠ comp not verified' : '⚠ location unknown')
  if (benign.length) parts.push(benign.map((b) => `${b === 'comp' ? 'comp' : 'location'} not posted`).join(' + '))
  return parts.join('; ')
}
// From prep's field_status ({compensation, working_location} each found/not_posted/capture_failed/
// conflicting). "not posted" = employer omitted it (benign); capture_failed/conflicting = we could
// not verify it (needs attention). Returns null if field_status is absent/unusable -> caller falls back.
function completenessFromFieldStatus(fs) {
  if (!fs || typeof fs !== 'object') return null
  const cat = (v) => (v === 'found' ? 'found' : v === 'not_posted' ? 'not_posted' : 'unknown')
  if (fs.compensation == null && fs.working_location == null) return null
  return completenessLabel(cat(fs.compensation), cat(fs.working_location))
}
// Fallback for batches with no manifest field_status: derive from the row itself. We cannot tell
// "not posted" from "capture_failed" here, so any missing field is treated as could-not-verify.
function fallbackCompleteness(compRange, location) {
  const comp = (compRange || '').trim()
  const loc = (location || '').trim()
  const compCat = (!comp || comp.includes('?')) ? 'unknown' : 'found'
  const locCat = (!loc || loc.toLowerCase() === 'unknown') ? 'unknown' : 'found'
  return completenessLabel(compCat, locCat)
}
// complete / benign (only "not posted") / attention (any "not verified"/"unknown") — used for the
// loud top-of-rankings summary (attention rows only). Mirrors make_rankings_xlsx.completeness_category.
function completenessCategory(v) {
  const s = (v || '').toLowerCase()
  if (!s) return null
  // A comp-source conflict is attention-worthy even when otherwise complete —
  // checked before 'complete'. Mirrors make_rankings_xlsx.completeness_category.
  if (s.includes('conflicting')) return 'attention'
  if (s.includes('complete')) return 'complete'
  if (s.includes('not verified') || s.includes('unknown')) return 'attention'
  if (s.includes('not posted')) return 'benign'
  return 'attention'
}

// Read the prep manifest ONCE (it records per-job field_status + missing_fields). Deterministic:
// the agent only returns raw file text; all parsing happens here. Map basename(output_path) ->
// field_status so each ranked row can be matched by its Job File name.
const batchRoot = discovery.root.includes('/3 - Source Material/')
  ? discovery.root.split('/3 - Source Material/')[0]
  : discovery.root
const manifestPath = `${batchRoot}/0 - Prep Report/prep-manifest.json`
let fsByFile = {}
{
  const MANIFEST_SCHEMA = {
    type: 'object', additionalProperties: false, required: ['text'],
    properties: { text: { type: 'string', description: 'Full raw JSON text of the manifest, or "" if it does not exist' } },
  }
  const man = await agent(
    `Read this file and return its FULL raw text verbatim in "text" (do not parse, summarize, or reformat). If the file does not exist, return "" for text.\n\n${manifestPath}`,
    { phase: 'Assemble', model: 'haiku', schema: MANIFEST_SCHEMA, label: 'read prep manifest' }
  )
  try {
    if (man && man.text && man.text.trim()) {
      const parsed = JSON.parse(man.text)
      for (const e of (parsed.entries || [])) {
        const out = e.output_path || ''
        const base = out.replace(/\/+$/, '').split('/').pop()
        if (base && e.field_status) fsByFile[base] = e.field_status
      }
    }
  } catch (_) { fsByFile = {} }
}

// ---- Compute final score + status in code (deterministic) ----
function statusFor(score) {
  if (score >= 80) return 'Apply ASAP: High Prio'
  if (score >= 70) return 'Apply Eventually: Apply If Time'
  if (score >= 60) return 'Apply Eventually: Backup Lane'
  return 'Apply Eventually: Or Skip It'
}
// Lane taxonomy normalizer — norm_contracts.py `normalize_lane` is the canonical implementation
// (the post-scoring CLI pass + make_rankings_xlsx.py both re-run it, so nothing off-taxonomy can
// survive into the final artifacts); keep this JS copy in sync. Rules: canonical buckets are
// Health / Consumer / Work / Other — "Work Tools - X" repairs to "Work - X" and bare "Work Tools"
// to "Work" (the bucket was renamed 2026-07-29; Lane Fit's candidate lane NAMES are user data and
// are untouched). Enforce "<Bucket> - <descriptor>" spacing, and force the exact
// "Health - Mental Health" spelling — no extra qualifier words — so the Lane column stays a clean,
// filterable taxonomy AND so the spreadsheet's lane_color() can key off it exactly.
function normalizeLane(lane) {
  const s = (lane || '').trim().replace(/\s+/g, ' ')
  const m = s.match(/^(health|consumer|work tools|work|other)\s*[-–—]\s*(.+)$/i)
  if (m) {
    let bucket = m[1].toLowerCase() === 'work tools' ? 'Work'
      : m[1].charAt(0).toUpperCase() + m[1].slice(1).toLowerCase()
    const desc = m[2].trim()
    if (bucket === 'Health' && /mental health/i.test(desc)) return 'Health - Mental Health'
    return `${bucket} - ${desc}`
  }
  if (/^work tools$/i.test(s)) return 'Work'
  return s
}
// HARD STOP (Jessica, 7/16/26): a job whose content the scoring agent could NOT verify as a
// real posting must never show a normal-looking score — that's exactly how a 488KB capture of
// Microsoft careers-site JS theme boilerplate got a final score of 44 and looked legitimate
// until she caught it by hand. Blank the score entirely and force a loud, unmissable status
// instead of a number that invites trust. This must survive downstream: make_rankings_xlsx.py
// gives this status its own unmissable fill, separate from the normal score-band colors.
const NEEDS_REFETCH_STATUS = '⚠️ NEEDS RE-FETCH — content not verified'
for (const r of rows) {
  r.lane = normalizeLane(r.lane)
  if (r.content_verified === false) {
    r.final_score = null
    r.desire_score = null
    r.market_perception_score = null
    r.company_style_score = null
    r.practicality_score = null
    r.status = NEEDS_REFETCH_STATUS
    r.top_concerns = `⚠️ FETCH VERIFICATION FAILED: ${r.content_issue || 'agent could not confirm this file contains real job-posting content'}. This row was NOT scored — re-fetch (try a different method) or paste the real posting text, then re-run vetting.` +
      (r.top_concerns ? ` | (original notes: ${r.top_concerns})` : '')
  } else {
    r.final_score = Math.round(
      r.desire_score * W.desire +
      r.market_perception_score * W.market +
      r.company_style_score * W.style +
      r.practicality_score * W.practicality
    )
    r.status = statusFor(r.final_score)
  }
  r._comp_fit = compFitLabel(r.comp_range, CFG)
  r._completeness = completenessFromFieldStatus(fsByFile[r.job_file]) || fallbackCompleteness(r.comp_range, r.location)
}
// Unverified rows float to the very top — impossible to miss, not buried at the bottom where a
// null score would otherwise sort.
rows.sort((a, b) => (b.final_score ?? Infinity) - (a.final_score ?? Infinity))
const unverifiedCount = rows.filter((r) => r.content_verified === false).length
if (unverifiedCount > 0) {
  log(`⚠️ ${unverifiedCount} job(s) FAILED content verification and were NOT scored — see "${NEEDS_REFETCH_STATUS}" rows at the top of the rankings.`)
}

// ---- Build CSV (deterministic quoting) ----
function csvCell(v) {
  const s = (v === undefined || v === null) ? '' : String(v)
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}
const laneFitStr = (lf) => lf ? `${lf.primary_lane} (${lf.confidence})${lf.secondary_lane ? ' · +' + lf.secondary_lane : ''}` : ''

// 28-column tracker layout, exact order: essential job info (incl. `Posted`, the employer's own
// publication date, right after Comp Range so the human-scannable block stays contiguous and ahead
// of the editable columns) -> the 3 human-editable workflow columns -> the SCORE BLOCK (5 columns,
// contiguous) -> notes (the practicality dimension's own notes column first, immediately after its
// score, then the mission/scope/reasons/concerns notes) -> Job File -> Base Resume Used (filled later by the tailor step; blank at
// vet time) -> AI fit detail. CSV and XLSX share this exact header set + order. The 5 score-column
// labels are DYNAMIC — resolved above from score-dimensions.json (or the candidate's scoring card,
// where it overrides weights).
// `Posted` is written BLANK here on purpose: it is not model output. The norm_contracts pass below
// fills it by reading each row's captured job file, which is also what back-fills an old CSV.
// STATIC (not derived from LABELS.practicality) on purpose: the other notes headers are static
// too, and the Python side (norm_contracts.py / make_rankings_xlsx.py) has to locate this column
// by an exact name that can't shift when a candidate's scoring card relabels the dimension.
const PRACTICALITY_NOTES_HEADER = 'Comp + Lifestyle Fit Notes'
// CSV and XLSX share this exact
// header set + order, and norm_contracts.normalize_rankings_csv MIGRATES any older CSV to it (rename
// -> drop -> insert -> reorder, joined by header NAME so no column's data ever shifts).
// `Location Fit` was REMOVED as redundant with `Working Location`: the canonical location grammar
// already encodes remote/metro/cadence, both columns carried the same 4-hex fill, and a second
// derived label was one more thing to keep in sync for no added signal.
// The 5 score-column labels are DYNAMIC (resolved above from score-dimensions.json), so a candidate
// who relabels a dimension relabels those headers with it; the defaults spell the contract exactly.
// THE COLUMN CONTRACT (order authoritative; the two ATS date columns merged into
// `Posting Last Update` on 2026-07-31).
const HEADERS = [
  'Applied Date? [You Fill In]', 'Status? [You Change]', 'Lane', 'Company', 'Job Post Title + Link',
  'Working Location', 'Comp Range',
  'Have Intro? [You Add]', 'Your Notes? [You Add]', 'Decline/Down Date? [You Add]',
  LABELS.final, LABELS.market, LABELS.desire, LABELS.style, LABELS.practicality,
  // How recently the ATS touched the posting: its last-updated date when published,
  // else its first-posted date, else `Unknown`. Read back out of the capture by the
  // norm_contracts pass — never the JAIL capture date, never inferred. Written as the
  // `Unknown` placeholder here (never blank). The two source dates remain separate in
  // the capture and the manifest; this column is a DISPLAY merge.
  'Posting Last Update',
  'Top Reasons Notes', 'Top Concerns Notes', 'Profile Score Notes', 'Your Desire Score Notes',
  // The practicality dimension's prose companion. It exists because that rationale used to be
  // written into `Comp Fit` — a contract-owned, machine-derived column — where the norm_contracts
  // pass correctly re-derived the label and destroyed the prose. Now it has a column of its own.
  PRACTICALITY_NOTES_HEADER,
  'Lane Fit', 'Comp Fit', 'Data Completeness', 'Job File',
  // Both blank at vet time and filled in later by the downstream steps, via
  // 03-VETTING/update_rankings_row.py: 'Tailored? (Base Resume)' by tailor-jobs (then the exact
  // base-resume name), 'Cover Letter Drafted?' by the cover-letter workflow (then `Yes`). The `?`
  // in these two headers is NOT a human-managed marker — only [You Fill In]/[You Change]/[You Add].
  'Tailored? (Base Resume)', 'Cover Letter Drafted?',
  // The resume-comparison block (2026-07-31), appended as a unit at the end so the tracker's
  // existing reading order is untouched. ALL FOUR are blank at vet time and stay blank until
  // the tailor step's comparison pass writes them via update_rankings_row.py.
  //
  // These are NOT a fifth ranking dimension and never feed the FINAL Weighted Score. The four
  // scored dimensions judge the JOB; `How They May See Your Profile` in particular is scored
  // from the candidate's canonical profile and the posting, and reads no resume at all. This
  // block judges the DOCUMENT: what the actual selected base resume communicates vs. what the
  // fully-tailored version would, with the delta as the only number that says whether tailoring
  // this job is worth the effort. `How They May See Your Profile` is not a ceiling on them.
  'Base Resume Score', 'Improved Resume Score', 'Resume Improvement Delta', 'Why It Improves',
]
// The CSV is CLEAN DATA ONLY — header + one row per job, in final-score order. No section-divider
// rows and no pre-grouping: that keeps the data sortable (no merged cells) and lets a user paste
// rows into their own tracker without dragging along duplicate dividers. The XLSX adds a separate
// section-color legend block + a Status dropdown; the user sorts/groups when they want.
function dataCells(r) {
  return [
    '', r.status, r.lane, r.company, r.title_and_link,
    r.location, r.comp_range,
    '', '', '',
    r.final_score, r.market_perception_score, r.desire_score, r.company_style_score, r.practicality_score,
    // Never blank, never the capture date, never inferred: the placeholder the
    // norm_contracts pass overwrites only with a VERIFIED ATS date.
    UNKNOWN_POSTED_DATE,
    r.top_reasons, r.top_concerns, r.scope_fit_notes, r.mission_fit_notes,
    r.comp_lifestyle_fit_notes,
    laneFitStr(r.lane_fit), r._comp_fit, r._completeness, r.job_file, '', '',
    // Resume-comparison block — written later by the tailor step, never at vet time.
    '', '', '', '',
  ]
}
const csvLines = [HEADERS.map(csvCell).join(',')]
for (const r of rows) csvLines.push(dataCells(r).map(csvCell).join(','))
const csvContent = csvLines.join('\n') + '\n'

// ---- Build Markdown (sorted desc) ----
const quarantinedN = (discovery && discovery.quarantined) || 0
const qNote = quarantinedN > 0 ? `> Note: ${quarantinedN} thin/failed post(s) were quarantined by prep and were NOT ranked (see "0 - Prep Report/"). Only usable posts are ranked below.\n` : ''
// Loud data-completeness summary line: which rows' scores were computed against comp/location that
// could NOT be verified (skips pure "not posted" — a benign employer omission, not our capture gap).
const incompleteRows = rows.filter((r) => r.content_verified !== false && completenessCategory(r._completeness) === 'attention')
const complSummary = incompleteRows.length
  ? `> ⚠️ **Incomplete captures (${incompleteRows.length}):** ${incompleteRows.map((r) => `${r.company} — ${r.title_and_link.split(' | ')[0]} (${(r._completeness || '').replace(/^⚠\s*/, '')})`).join('; ')}\n`
  : `> ✓ Data completeness: all captures complete.\n`
const mdParts = [`# Job Rankings\n\n${rows.length} jobs scored, highest priority first.\n${complSummary}${qNote}`]
const fmtScore = (v) => v === null || v === undefined ? '—' : v
// The resume-comparison line is OMITTED at vet time rather than printed as em-dashes: it is blank
// for every job until that job is tailored, and 55 placeholder lines would be pure noise. The
// tailor step inserts the real line into this Markdown in place (update_rankings_row.py), which is
// what keeps the CSV, XLSX and Markdown from disagreeing. Guarded here so a caller that does have
// the values (a re-vet after tailoring) still renders them.
const resumeCompLine = (r) => (
  r.base_resume_score === null || r.base_resume_score === undefined ? ''
    : `\n- **Resume improvement:** base ${r.base_resume_score} → improved ${r.improved_resume_score} (delta +${r.resume_improvement_delta}).${r.why_it_improves ? ` ${r.why_it_improves}` : ''}`
)
for (const r of rows) {
  mdParts.push(
`## ${fmtScore(r.final_score)} — ${r.company}: ${r.title_and_link.split(' | ')[0]}${r.content_verified === false ? '  ⚠️ NOT SCORED — SEE BELOW' : ''}

- **Status:** ${r.status}
- **Lane:** ${r.lane}  |  **Lane fit:** ${laneFitStr(r.lane_fit)}
- **Location:** ${r.location}  |  **Comp:** ${r.comp_range}
- **Scores:** ${LABELS.desire} ${fmtScore(r.desire_score)} / ${LABELS.market} ${fmtScore(r.market_perception_score)} / ${LABELS.style} ${fmtScore(r.company_style_score)} / ${LABELS.practicality} ${fmtScore(r.practicality_score)} → **${LABELS.final} ${fmtScore(r.final_score)}**
- **${LABELS.practicality} notes:** ${r.comp_lifestyle_fit_notes || '—'}
- **Mission fit:** ${r.mission_fit_notes}
- **Scope fit:** ${r.scope_fit_notes}
- **Top reasons:** ${r.top_reasons}
- **Top concerns:** ${r.top_concerns}
- **File:** ${r.job_file}${resumeCompLine(r)}
`)
}
const mdContent = mdParts.join('\n')

// ---- Derive output filenames: <batch>-rankings.* written into the out-dir ----
// Name from BATCH_NAME if given (e.g. "06-02-26"), else the scored folder's name.
// Write into OUT_DIR if given (e.g. ".../1 - Rankings"), else alongside the jobs.
const folderName = BATCH_NAME || discovery.root.replace(/\/+$/, '').split('/').pop()
const outRoot = (OUT_DIR || discovery.root).replace(/\/+$/, '')
const csvPath = `${outRoot}/${folderName}-rankings.csv`
const mdPath = `${outRoot}/${folderName}-rankings.md`
const metaPath = `${outRoot}/${folderName}-rankings.meta.json`

// ---- Per-run score metadata (the bridge to make_rankings_xlsx.py, a separate Python process that
// can't share JS objects directly) — the EFFECTIVE labels/weights/definitions for THIS run, so the
// Instructions tab can render them dynamically instead of hardcoding a second copy. ----
const metaContent = JSON.stringify({
  order: DIMS.order || FALLBACK_DIMS.order,
  final: { label: LABELS.final },
  desire: { label: LABELS.desire, definition: DIMS.desire.definition, weight_pct: Math.round(W.desire * 100) },
  market: { label: LABELS.market, definition: DIMS.market.definition, weight_pct: Math.round(W.market * 100) },
  style: { label: LABELS.style, definition: DIMS.style.definition, weight_pct: Math.round(W.style * 100) },
  practicality: { label: LABELS.practicality, definition: DIMS.practicality.definition, weight_pct: Math.round(W.practicality * 100) },
  // The resume-comparison block is described here but deliberately kept OUT of `order`:
  // `order` drives the weighted-score math and the XLSX sub-score color ramp, and these are
  // neither ranking dimensions nor weighted. They carry no weight_pct for the same reason.
  resume_comparison: {
    columns: {
      base: 'Base Resume Score',
      improved: 'Improved Resume Score',
      delta: 'Resume Improvement Delta',
      why: 'Why It Improves',
    },
    scale: '0-100, in increments of 5 only',
    step: 5,
    definition: 'How strongly a specific resume DOCUMENT would position the candidate for this '
      + 'job in the employer\'s eyes: the actual selected base resume vs. the best version that '
      + 'would exist if every tailoring recommendation were implemented. Both are scored in one '
      + 'comparison pass against the same hiring thesis. The delta is improved minus base and is '
      + 'never negative, because the improved version may always retain the base unchanged. '
      + 'These do not feed the FINAL Weighted Score, and "How They May See Your Profile" '
      + '(scored from the canonical profile, not from any resume) is not a ceiling on them.',
    written_by: 'the tailor step\'s comparison pass, via 03-VETTING/update_rankings_row.py',
  },
}, null, 2) + '\n'

// ---- Phase 3: write the three files ----
phase('Assemble')
const WRITE_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['wrote'],
  properties: { wrote: { type: 'array', items: { type: 'string' } } },
}
await agent(
  `Write these three files EXACTLY as given, overwriting if they exist. Do not modify the content.

=== FILE 1: ${csvPath} ===
${csvContent}
=== END FILE 1 ===

=== FILE 2: ${mdPath} ===
${mdContent}
=== END FILE 2 ===

=== FILE 3: ${metaPath} ===
${metaContent}
=== END FILE 3 ===

Return the list of paths you wrote.`,
  { phase: 'Assemble', model: 'haiku', schema: WRITE_SCHEMA, label: 'write outputs' }
)

// ---- Mechanically normalize the output-contract columns of the CSV (repair-or-fail-loudly) ----
// norm_contracts.py is the ONE canonical normalizer (no JS port): it enforces the Working Location
// grammar, the Comp Range N-N format (re-deriving Comp Fit via the midpoint rule), and the Lane
// taxonomy on the CSV in place, printing every repair, BEFORE the XLSX build. The same pass fills
// the `Posted` column from each row's captured `Posted:` provenance line.
const NORM_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['ok'],
  properties: { ok: { type: 'boolean' }, output: { type: 'string', description: 'repair/warning lines the script printed, or ""' }, message: { type: 'string' } },
}
const normRes = await agent(
  `Run this EXACT shell command from the project root (it uses the project venv if present, else python3):

PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"; "$PY" ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/norm_contracts.py --normalize-rankings-csv "${csvPath}" --config jail.config.json --score-labels ${JSON.stringify(JSON.stringify(LABELS))}

Do not edit the script or the CSV yourself. Return ok:true if it exited without a Python traceback; put every "[norm_contracts]" repair/warning line it printed in "output" (or "" if none); on failure return ok:false with the error text in message.`,
  { phase: 'Assemble', model: 'haiku', schema: NORM_SCHEMA, label: 'normalize contract columns' }
)
if (normRes && normRes.output && normRes.output.trim()) log(normRes.output.trim())
if (!normRes || !normRes.ok) log(`⚠️ norm_contracts normalization pass FAILED — the CSV/XLSX may contain non-canonical values. ${(normRes && normRes.message) || ''}`)

// ---- Build the polished, conditionally-formatted XLSX from the CSV ----
const xlsxPath = csvPath.replace(/\.csv$/i, '.xlsx')
const XLSX_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['ok'],
  properties: { ok: { type: 'boolean' }, message: { type: 'string' } },
}
const xlsxRes = await agent(
  `Run this EXACT shell command from the project root to build the formatted spreadsheet (it uses the project venv if present, else python3):

PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"; "$PY" ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/make_rankings_xlsx.py "${csvPath}" "${xlsxPath}" --config jail.config.json --quarantined ${quarantinedN}

Do not edit the script. Return ok:true if it printed a "Wrote ..." line with no Python traceback; otherwise ok:false with the error text in message.`,
  { phase: 'Assemble', model: 'haiku', schema: XLSX_SCHEMA, label: 'build xlsx' }
)

return {
  folder: discovery.root,
  jobs_scored: rows.length,
  quarantined: quarantinedN,
  csv: csvPath,
  markdown: mdPath,
  meta: metaPath,
  xlsx: (xlsxRes && xlsxRes.ok) ? xlsxPath : null,
  top: rows.slice(0, 5).map((r) => `${r.final_score} ${r.company} — ${r.status}`),
  // Full ranking (desc) so a parent workflow can pick which jobs to tailor.
  ranked: rows.map((r) => ({
    final_score: r.final_score,
    status: r.status,
    company: r.company,
    title_and_link: r.title_and_link,
    job_file: r.job_file,
    abs_path: r.abs_path,
  })),
}
