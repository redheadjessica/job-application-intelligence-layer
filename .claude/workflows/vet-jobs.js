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

const SCORE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: [
    'content_verified', 'content_issue',
    'company', 'title_and_link', 'location', 'comp_range', 'lane', 'lane_fit',
    'desire_score', 'market_perception_score', 'company_style_score', 'practicality_score',
    'mission_fit_notes', 'scope_fit_notes', 'top_reasons', 'top_concerns',
  ],
  properties: {
    // HARD STOP (Jessica, 7/16/26): a job must never be scored against content nobody
    // has confirmed is the real posting. Fill these FIRST, before any scoring. If false,
    // still fill every score field below with your best-effort honest read AS FAR AS THE
    // TEXT ALLOWS — the assembler below is what actually blanks the scores and flags the
    // row; you must not silently fabricate confident-looking numbers from a title alone.
    content_verified: { type: 'boolean', description: 'true only if this file contains an ACTUAL job posting body you can read — real responsibilities/qualifications/role description, not just navigation chrome, theme/config JSON, a login/apply shell, or a title with no body. If you cannot find genuine posting content in the file, set this to false.' },
    content_issue: { type: ['string', 'null'], description: 'If content_verified is false, describe exactly what is wrong (e.g. "file is ~490KB of JS theme config and navbar JSON, no responsibilities/qualifications text found") so a human knows this needs a re-fetch. Null if content_verified is true.' },
    company: { type: 'string' },
    title_and_link: { type: 'string', description: 'Role Title | URL, or just the title if no URL' },
    location: { type: 'string', description: 'Normalized location. RULES: fully remote -> "Remote". Remote but restricted to certain US states -> "Remote (states: CA/NY/TX/...)". In-office/hybrid in NYC -> "IRL NYC - N days" where N is the required in-office days per week if stated, else "unknown days"; append specific days if named, e.g. "IRL NYC - 3 days (Mon/Tue/Thu standard)". In-office elsewhere -> "IRL <City> - N days" (or "IRL <City> - unknown days" if arrangement/day-count is not stated). ABBREVIATE major cities to their common short form: "New York City"/"New York, NY" -> "NYC", "San Francisco" -> "SF" (use other standard short forms similarly, e.g. "LA", "DC" — only when unambiguous; keep less-common city names spelled out). MULTI-CITY postings (the role can be based in any of several named cities): join them with "/" in the candidate\'s preferred order (see the <preferences> location.city_priority list — candidate-priority cities first, in that order, then any other named cities in the posting\'s own order), e.g. "NYC/SF/Austin - 3 days". IMPORTANT: if a city or office location is named ANYWHERE in the posting (title, header, comp-transparency line, etc.) but the remote/hybrid/onsite arrangement or day count is not stated, still use "IRL <City> - unknown days" — do NOT fall back to bare "Unknown" just because the arrangement type is unclear; a named city is real signal, not nothing. Only use "Unknown" when the posting gives NO location signal at all — no city, no remote/hybrid/onsite mention, nothing. ALWAYS use "IRL" (never "Hybrid"). A bare "Location: <City>" line is usually the company HQ, NOT a relocation requirement -> only treat as in-office if the posting actually requires on-site presence; otherwise look for the real workplace type (Remote/Hybrid/On-site) and the exact required day count.' },
    comp_range: { type: 'string', description: 'lowest-highest in thousands, no $ or commas, e.g. 190-210, or ?? if unknown' },
    lane: { type: 'string', description: 'The job’s category as "<Bucket> - <Subcategory>", in the job’s OWN terms, independent of the candidate. Bucket = the closest fit from this small, reusable set: Health, Consumer, Work Tools, Other (introduce a new bucket only if truly none of these fit — keep the bucket set small). Subcategory = the most specific 1-4 word descriptor for what the job actually IS within that bucket. Examples: "Health - DTC Supplements", "Health - Provider Tools", "Health - Consumer Wellness", "Consumer - Home Sharing", "Work Tools - Legal", "Work Tools - Collaboration", "Work Tools - Consumer Research", "Other - Fintech". Reuse an existing subcategory phrasing across jobs with the same fit rather than inventing near-duplicate wording (always "Work Tools - Collaboration" for general collab/productivity software, not sometimes "Work Tools - Collab Software") — the point is a consistent, scalable taxonomy, not a one-off description. EXACT SPELLING REQUIRED for mental health: any job whose core product is mental/behavioral health must be lane EXACTLY "Health - Mental Health" — no extra qualifier words (not "Health - Consumer Mental Health", not "Health - Mental Health (Member Growth)"); put any extra nuance in scope_notes instead, never in the lane string.' },
    lane_fit: {
      type: 'object', additionalProperties: false,
      required: ['primary_lane', 'secondary_lane', 'confidence', 'note'],
      properties: {
        primary_lane: { type: 'string', description: 'EXACTLY one of the candidate’s priority-lane names (verbatim from the profile), or "Outside lanes" if the role fits none of them.' },
        secondary_lane: { type: ['string', 'null'] },
        confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
        note: { type: 'string', description: 'one short phrase on why it fits or does not' },
      },
    },
    desire_score: { type: 'integer', minimum: 0, maximum: 100, description: 'How much the candidate would want this job — mission fit, role excitement, domain alignment' },
    market_perception_score: { type: 'integer', minimum: 0, maximum: 100 },
    company_style_score: { type: 'integer', minimum: 0, maximum: 100, description: 'How well the company culture, stage, and working style fit the candidate' },
    practicality_score: { type: 'integer', minimum: 0, maximum: 100, description: 'How practical/livable the job is — comp relative to targets, location/remote fit, logistics' },
    // Human-readable, plain-English, ONE sentence each (Jessica, 7/16/26 — the previous style, with
    // sub-factor math spelled out like "Mission 27/30 + Role 16/30 + Brand 11/20 = 69", read as
    // dense and unfriendly). No "=", no fractions, no "+", no jargon — write it the way you'd
    // explain your reasoning out loud to the candidate in one breath. This applies to every ranking
    // run this engine produces, for any user, not just this one.
    mission_fit_notes: { type: 'string', description: 'ONE plain-English sentence explaining the Desire score — why this pulls or doesn\'t pull the candidate. No sub-factor math, no "=", "/", or "+" notation. Example: "A strong AI-forward growth role at a brand they\'d be excited to join, though it\'s enterprise L&D work rather than their preferred consumer-product space." NOT: "Desire = 66 (Mission 11/30 + Role 25/30 + Brand 18/20 + Culture 10/15 + Stage 2/5)."' },
    scope_fit_notes: { type: 'string', description: 'ONE plain-English sentence explaining the Profile Fit score — how convincingly the candidate\'s career tells the story this role wants. No sub-factor math, no "=", "/", or "+" notation. Example: "A platform-PM track record that maps closely onto this role\'s core asks, with AI-feature building the one area they\'d need to speak to via analogy rather than direct experience." NOT: "Profile Fit = 87. Hiring thesis: ... Thesis-defining centrals: (1) ... (2) ... (3) ..."' },
    // Optional deeper reasoning — the sub-factor math / hiring-thesis breakdown that USED to live in
    // mission_fit_notes/scope_fit_notes. Only the Markdown report shows this (indented, collapsible
    // by not reading past the summary line); the CSV/XLSX tracker — what a human actually scans —
    // never shows it. Fill it in when you want the detailed reasoning preserved for someone auditing
    // the score later; null is fine when the one-sentence note already says everything worth saying.
    mission_fit_detail: { type: ['string', 'null'], description: 'Optional: the full sub-factor math / detailed reasoning behind desire_score, for anyone auditing the score later. Markdown-report-only — never shown in the spreadsheet. Null if the one-sentence mission_fit_notes already covers it.' },
    scope_fit_detail: { type: ['string', 'null'], description: 'Optional: the full hiring-thesis-test reasoning behind market_perception_score, for anyone auditing the score later. Markdown-report-only — never shown in the spreadsheet. Null if the one-sentence scope_fit_notes already covers it.' },
    top_reasons: { type: 'string', description: 'semicolon-separated phrases' },
    top_concerns: { type: 'string', description: 'semicolon-separated phrases' },
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
  style: { label: 'Culture Fit', schema_key: 'company_style_score', default_weight: 20,
    definition: "Estimates how well the company's apparent working style, values, product culture, and environment may suit you, based on the evidence actually available. Job postings provide incomplete culture evidence. When little reliable information is available, this score should remain closer to neutral and should be treated as lower-confidence." },
  practicality: { label: 'Comp + Lifestyle Fit', schema_key: 'practicality_score', default_weight: 15,
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

// Parse the structured config once — used to write candidate-relative Comp Fit / Location Fit
// LABELS into the CSV (single source of this math; make_rankings_xlsx.py only maps label -> color).
let CFG = {}
try { CFG = (refs && refs.config && refs.config.trim()) ? JSON.parse(refs.config) : {} } catch (_) { CFG = {} }

// ---- First-run completeness nudge ----
// Comp Fit / Location Fit / Lane coloring all fall back to neutral/grey when these are missing —
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
    log(`⚠ jail.config.json is missing: ${missing}. Comp Fit / Location Fit / Lane coloring will be neutral until this is filled in — run /intake (or its update mode) to complete it.`)
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
  - desire_score: how much the candidate would want this role — mission fit, role excitement, domain alignment, personal pull.
  - market_perception_score: how strong a candidate they would appear to this employer — experience match, credibility, likely recruiter reaction.
  - company_style_score: how well the company culture, stage, and working style fit the candidate.
  - practicality_score: how livable/practical the job is — comp relative to the candidate's targets, location/remote fit, logistics, quality of life. Use the <preferences> block (comp target/floor, location arrangement ratings) when present to sharpen this; if preferences are absent, fall back to the profile prose. Preferences inform — they do not override the full rubric/profile.
- Do NOT compute the final score or status — that is handled downstream. Just return the four sub-scores and the fields below.
- Be decisive. Don't over-index on title. Reflect comp/location tradeoffs in practicality_score, not by skipping.
- comp_range: lowest-highest base across all bands shown, in whole thousands, no $ or commas (e.g. 190-210); "??" if unknown.
- location: normalize per the schema rules. CAREFULLY determine the real workplace type from the posting: look for explicit Remote / Hybrid / On-site tags, the exact required in-office DAYS PER WEEK, and any US-state hiring restrictions. Use "IRL NYC - N days" with the exact day count when stated ("unknown days" if not) — NEVER just "Hybrid". Abbreviate major cities to their common short form (NYC, SF, LA, DC, etc. — only when unambiguous). If the posting names MULTIPLE candidate office cities, join them with "/" in the candidate's city_priority order from <preferences> (priority cities first, in that order; any other named cities after, in the posting's own order) — e.g. "NYC/SF/Austin - 3 days". If a city/office location is named ANYWHERE in the posting but the arrangement or day count isn't stated, still output "IRL <City> - unknown days" — a named city is real signal; do NOT collapse it to bare "Unknown". Only use "Unknown" when the posting gives no location signal at all. **If the file has its own "Location: ..." line at the very top (before "--- JOB TEXT START ---") — the fetcher's own structured field for this posting — treat it as authoritative ground truth for the city/region; don't second-guess or override it from body text.** For a bare "Location: <City>" line found INSIDE the job description body (not that top structured field), treat it as the company HQ, not a relocation requirement, unless the posting actually requires on-site presence. If remote but restricted to specific US states, list them as "Remote (states: ...)".
- title_and_link: "Role Title | URL" if a URL is present, else just the title.
- lane: the job's category as "<Bucket> - <Subcategory>", in the job's OWN terms — NOT mapped to the candidate's lanes. Bucket = closest fit from Health / Consumer / Work Tools / Other (add a new bucket only if truly none fit — keep this set small and reusable). Subcategory = the most specific 1-4 word descriptor, e.g. "Health - DTC Supplements", "Health - Provider Tools", "Health - Consumer Wellness", "Consumer - Home Sharing", "Work Tools - Legal", "Work Tools - Collaboration", "Work Tools - Consumer Research", "Other - Fintech". Reuse existing subcategory phrasing for the same kind of job rather than inventing near-duplicate wording — consistency across jobs matters more than precision on any one job. Mental/behavioral health jobs MUST use the exact string "Health - Mental Health" — no extra qualifier words appended.
- lane_fit: how that job-lane maps to the CANDIDATE's priority lanes — candidate-relative and honest. { primary_lane: EXACTLY one of the candidate's priority-lane names (verbatim from the profile), or "Outside lanes" if it fits none; secondary_lane (or null); confidence ("high"/"medium"/"low"); note (one short phrase) }. If the role is not one of the candidate's lanes, primary_lane = "Outside lanes" (even when the domain sounds related). Do NOT inflate — it is surfaced for the candidate, not added to the score.
- mission_fit_notes / scope_fit_notes: ONE plain-English sentence each, written the way you'd say it out loud — no sub-factor math, no "=", "/", or "+" notation, no "Mission 27/30 + Role 16/30..." breakdowns. If you want the detailed reasoning preserved for later auditing, put THAT in mission_fit_detail / scope_fit_detail instead (optional, null if not needed) — never in the human-facing notes fields.
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
function compFitLabel(text, cfg) {
  const t = (text || '').trim()
  const nums = (t.match(/\d+/g) || []).map(Number)
  if (!t || t.includes('?') || nums.length === 0) return 'Unknown'
  const comp = (cfg && cfg.comp) || {}
  const floor = comp.floor_base, target = comp.target_base
  if (floor == null && target == null) return 'No comp prefs'
  const high = Math.max(...nums)
  if (floor != null && high < floor) return 'Below floor'
  if (target != null && high >= target) return 'Meets/above target'
  if (target != null) return 'Near target'
  return 'Above floor'
}
function locationFitLabel(text, cfg) {
  const loc = (text || '').trim().toLowerCase()
  const locp = (cfg && cfg.location) || {}
  const aliases = ((locp.home_metro_aliases) || []).filter(Boolean).map((a) => a.toLowerCase())
  const home = (locp.home_metro || '').trim().toLowerCase()
  if (home) aliases.push(home)
  // Check IRL/onsite/hybrid BEFORE the "unknown"/"unclear" bail-out — a value like
  // "IRL NYC - unknown days" has a real, known city with only the day-count missing, and must not
  // be short-circuited to Unclear just because the substring "unknown" appears in "unknown days".
  if (!loc) return 'Unclear'
  if (loc.includes('remote')) return loc.includes('state') ? 'Remote (state-restricted)' : 'Remote'
  // A bare "<City> - N days" (no "IRL"/"hybrid"/"onsite" keyword) is still a real in-office signal —
  // don't fall through to Unclear just because the agent skipped the "IRL" prefix. Detect it via the
  // day-count pattern itself, or a recognized city name appearing without "remote".
  const hasDayCount = /\d+\s*day/.test(loc)
  const hasKnownCity = aliases.length && aliases.some((a) => loc.includes(a))
  if (['irl', 'onsite', 'on-site', 'hybrid', 'in-office', 'in office'].some((k) => loc.includes(k)) || hasDayCount || hasKnownCity) {
    const m = loc.match(/(\d+)\s*day/)
    const days = m ? Number(m[1]) : null
    const onsite = loc.includes('onsite') || loc.includes('on-site') || (days != null && days >= 5)
    const mode = onsite ? 'onsite' : 'hybrid'
    if (aliases.length && aliases.some((a) => loc.includes(a))) return `Home ${mode}`
    if (aliases.length) return `Other ${mode}`
    return `${mode.charAt(0).toUpperCase()}${mode.slice(1)} (home metro not set)`
  }
  if (loc.includes('unknown') || loc.includes('unclear')) return 'Unclear'
  return 'Unclear'
}

// ---- Compute final score + status in code (deterministic) ----
function statusFor(score) {
  if (score >= 80) return 'Apply ASAP: High Prio'
  if (score >= 70) return 'Apply Eventually: Apply If Time'
  if (score >= 60) return 'Apply Eventually: Backup Lane'
  return 'Apply Eventually: Or Skip It'
}
// Force the exact "Health - Mental Health" spelling — no extra qualifier words — whenever an agent
// scores a job into that subcategory (e.g. "Health - Consumer Mental Health"), so the Lane column
// stays a clean, filterable taxonomy AND so the spreadsheet's lane_color() can key off it exactly.
function normalizeLane(lane) {
  const s = (lane || '').trim()
  if (/^health\s*-\s*.*mental health/i.test(s)) return 'Health - Mental Health'
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
  r._loc_fit = locationFitLabel(r.location, CFG)
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

// 24-column tracker layout, exact order: essential job info -> the 3 human-editable workflow
// columns (positions 8-10) -> the SCORE BLOCK (5 columns, contiguous at positions 11-15) -> notes ->
// Job File -> Base Resume Used (filled later by the tailor step; blank at vet time) -> AI fit detail.
// CSV and XLSX share this exact header set + order. The 5 score-column labels are DYNAMIC — resolved
// above from score-dimensions.json (or the candidate's scoring card, where it overrides weights).
const HEADERS = [
  'Applied Date? [You Fill In]', 'Status? [You Change]', 'Lane', 'Company', 'Job Post Title + Link',
  'Working Location', 'Comp Range',
  'Have Intro? [You Add]', 'Your Notes? [You Add]', 'Decline/Down Date? [You Add]',
  LABELS.final, LABELS.market, LABELS.desire, LABELS.style, LABELS.practicality,
  'Mission Fit Notes', 'Scope Fit Notes', 'Top Reasons Notes', 'Top Concerns',
  'Job File', 'Base Resume Used', 'Lane Fit', 'Location Fit', 'Comp Fit',
  // Both blank at vet time and filled in later by the downstream steps, via
  // 03-VETTING/update_rankings_row.py: 'Base Resume Used' by tailor-jobs, 'Cover Letter?' by the
  // cover-letter workflow. (Before 7/16/26 'Base Resume Used' was written blank here and NOTHING
  // ever filled it — the tailor agent's recommended_base was returned and silently discarded.)
  'Cover Letter?',
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
    r.mission_fit_notes, r.scope_fit_notes, r.top_reasons, r.top_concerns,
    r.job_file, '', laneFitStr(r.lane_fit), r._loc_fit, r._comp_fit, '',
  ]
}
const csvLines = [HEADERS.map(csvCell).join(',')]
for (const r of rows) csvLines.push(dataCells(r).map(csvCell).join(','))
const csvContent = csvLines.join('\n') + '\n'

// ---- Build Markdown (sorted desc) ----
const quarantinedN = (discovery && discovery.quarantined) || 0
const qNote = quarantinedN > 0 ? `> Note: ${quarantinedN} thin/failed post(s) were quarantined by prep and were NOT ranked (see "0 - Prep Report/"). Only usable posts are ranked below.\n` : ''
const mdParts = [`# Job Rankings\n\n${rows.length} jobs scored, highest priority first.\n${qNote}`]
const fmtScore = (v) => v === null || v === undefined ? '—' : v
for (const r of rows) {
  mdParts.push(
`## ${fmtScore(r.final_score)} — ${r.company}: ${r.title_and_link.split(' | ')[0]}${r.content_verified === false ? '  ⚠️ NOT SCORED — SEE BELOW' : ''}

- **Status:** ${r.status}
- **Lane:** ${r.lane}  |  **Lane fit:** ${laneFitStr(r.lane_fit)}
- **Location:** ${r.location}  |  **Comp:** ${r.comp_range}
- **Scores:** ${LABELS.desire} ${fmtScore(r.desire_score)} / ${LABELS.market} ${fmtScore(r.market_perception_score)} / ${LABELS.style} ${fmtScore(r.company_style_score)} / ${LABELS.practicality} ${fmtScore(r.practicality_score)} → **${LABELS.final} ${fmtScore(r.final_score)}**
- **Mission fit:** ${r.mission_fit_notes}${r.mission_fit_detail ? `\n  - *Detail:* ${r.mission_fit_detail}` : ''}
- **Scope fit:** ${r.scope_fit_notes}${r.scope_fit_detail ? `\n  - *Detail:* ${r.scope_fit_detail}` : ''}
- **Top reasons:** ${r.top_reasons}
- **Top concerns:** ${r.top_concerns}
- **File:** ${r.job_file}
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
