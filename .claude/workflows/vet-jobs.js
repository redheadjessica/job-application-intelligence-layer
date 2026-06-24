export const meta = {
  name: 'vet-jobs',
  description: 'Score a dated batch folder of job descriptions in parallel (one agent per job), then assemble CSV + Markdown rankings into that same folder',
  whenToUse: 'Run a job-vetting batch fast. Pass the batch folder path as args, e.g. {folder: "03-VETTING/06-02-26"}.',
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
  throw new Error('Pass the batch folder path as args, e.g. {folder: "03-VETTING/06-02-26"} or just "03-VETTING/Old Runs/04-09-26".')
}
// Optional: write the rankings somewhere OTHER than the scored folder (e.g. a sibling
// "1 - Rankings/" tier), and name them after the batch rather than the source subfolder.
const OUT_DIR = (A && typeof A === 'object' && A.outDir) ? A.outDir : null
const BATCH_NAME = (A && typeof A === 'object' && A.batchName) ? A.batchName : null

// Rubric + profile live in the 03-VETTING/ subfolder of the merged project.
const RUBRIC = '03-VETTING/01-scoring-card.md'
const PROFILE = '03-VETTING/02-candidate-profile.md'

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
  },
}

const SCORE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: [
    'category', 'company', 'title_and_link', 'location', 'comp_range', 'lane',
    'desire_score', 'market_perception_score', 'company_style_score', 'practicality_score',
    'mission_fit_notes', 'scope_fit_notes', 'top_reasons', 'top_concerns',
  ],
  properties: {
    category: { type: 'string' },
    company: { type: 'string' },
    title_and_link: { type: 'string', description: 'Role Title | URL, or just the title if no URL' },
    location: { type: 'string', description: 'Normalized location. RULES: fully remote -> "Remote". Remote but restricted to certain US states -> "Remote (states: CA/NY/TX/...)". In-office/hybrid in NYC -> "IRL NYC - N days" where N is the required in-office days per week if stated, else "unknown days"; append specific days if named, e.g. "IRL NYC - 3 days (Mon/Tue/Thu standard)". In-office elsewhere -> "IRL <City> - N days". Unknown -> "Unknown". ALWAYS use "IRL" (never "Hybrid"). A bare "Location: <City>" line is usually the company HQ, NOT a relocation requirement -> only treat as in-office if the posting actually requires on-site presence; otherwise look for the real workplace type (Remote/Hybrid/On-site) and the exact required day count.' },
    comp_range: { type: 'string', description: 'lowest-highest in thousands, no $ or commas, e.g. 190-210, or ?? if unknown' },
    lane: { type: 'string', description: 'Which of the candidate’s priority lanes (from the profile), or "Outside lanes"' },
    desire_score: { type: 'integer', minimum: 0, maximum: 100, description: 'How much the candidate would want this job — mission fit, role excitement, domain alignment' },
    market_perception_score: { type: 'integer', minimum: 0, maximum: 100 },
    company_style_score: { type: 'integer', minimum: 0, maximum: 100, description: 'How well the company culture, stage, and working style fit the candidate' },
    practicality_score: { type: 'integer', minimum: 0, maximum: 100, description: 'How practical/livable the job is — comp relative to targets, location/remote fit, logistics' },
    mission_fit_notes: { type: 'string' },
    scope_fit_notes: { type: 'string' },
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
5. Return the absolute folder path as "root" and one entry per distinct job.`,
  { phase: 'Discover', model: 'haiku', schema: DISCOVER_SCHEMA, label: 'discover files' }
)

if (!discovery || !discovery.jobs || discovery.jobs.length === 0) {
  return { error: `No job files found in "${FOLDER}".`, folder: FOLDER }
}
log(`Found ${discovery.jobs.length} jobs in ${discovery.root} — scoring in parallel`)

// Load rubric + profile ONCE and inline them into every scoring prompt, instead of
// having all N scoring agents each re-read the same two files (N x 2 redundant reads).
const REFS_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['rubric', 'profile', 'weights'],
  properties: {
    rubric: { type: 'string' },
    profile: { type: 'string' },
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
  `Read these two files and return their FULL text verbatim (do not summarize or truncate):
- ${RUBRIC}  -> field "rubric"
- ${PROFILE} -> field "profile"

Also extract the FOUR dimension weights from the scoring card's section headers, which look like "(weight: NN%)". Return them as raw percentages in "weights", in the order the dimensions appear: 1st -> weights.desire, 2nd -> weights.market, 3rd -> weights.style, 4th -> weights.practicality (e.g. 35, 30, 20, 15). If the card does not clearly state weights, return 0 for all four.`,
  { phase: 'Discover', model: 'haiku', schema: REFS_SCHEMA, label: 'load rubric+profile' }
)
// Required-file guard (V2 template/instance split): the rubric + profile are GENERATED
// instances produced by /intake, not tracked templates. If they're missing/empty, stop with
// an actionable message rather than scoring against nothing.
const haveRefs = !!(refs && refs.rubric && refs.profile)
if (!haveRefs) {
  return {
    error: "I can't vet yet — your scoring card and candidate profile haven't been generated. They're created when you run /intake. Run /intake first to produce 03-VETTING/01-scoring-card.md and 03-VETTING/02-candidate-profile.md, then re-run this batch.",
    missing: [RUBRIC, PROFILE].filter((p, i) => !(i === 0 ? (refs && refs.rubric) : (refs && refs.profile))),
  }
}
const refsBlock = `Use this rubric and profile (already loaded — do NOT open any other files for these):

<scoring-card>
${refs.rubric}
</scoring-card>

<profile>
${refs.profile}
</profile>`

// ---- Phase 2: score each job concurrently ----
phase('Score')
const scored = await parallel(discovery.jobs.map((job) => async () => {
  const result = await agent(
    `You are scoring ONE job for the candidate's vetting system.

${refsBlock}

Now read ONLY this job description file and score it:
${job.abs_path}

Scoring rules:
- Four scores, each an INTEGER 0-100: desire_score, market_perception_score, company_style_score, practicality_score.
  - desire_score: how much the candidate would want this role — mission fit, role excitement, domain alignment, personal pull.
  - market_perception_score: how strong a candidate they would appear to this employer — experience match, credibility, likely recruiter reaction.
  - company_style_score: how well the company culture, stage, and working style fit the candidate.
  - practicality_score: how livable/practical the job is — comp relative to the candidate's targets, location/remote fit, logistics, quality of life.
- Do NOT compute the final score or status — that is handled downstream. Just return the four sub-scores and the fields below.
- Be decisive. Don't over-index on title. Reflect comp/location tradeoffs in practicality_score, not by skipping.
- comp_range: lowest-highest base across all bands shown, in whole thousands, no $ or commas (e.g. 190-210); "??" if unknown.
- location: normalize per the schema rules. CAREFULLY determine the real workplace type from the posting: look for explicit Remote / Hybrid / On-site tags, the exact required in-office DAYS PER WEEK, and any US-state hiring restrictions. Use "IRL NYC - N days" with the exact day count when stated ("unknown days" if not) — NEVER just "Hybrid". Treat a bare "Location: <City>" line as the company HQ, not a relocation requirement, unless the posting actually requires on-site presence. If remote but restricted to specific US states, list them as "Remote (states: ...)".
- category: most specific fit from the candidate's priority-lane taxonomy (see profile); use a broad lane only if the subcategory is unclear.
- title_and_link: "Role Title | URL" if a URL is present, else just the title.
- lane: which of the candidate's priority lanes it fits, or "Outside lanes".
- mission_fit_notes / scope_fit_notes: one tight phrase each.
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

// ---- Compute final score + status in code (deterministic) ----
function statusFor(score) {
  if (score >= 80) return 'Apply ASAP: High Prio'
  if (score >= 70) return 'Apply Eventually: Apply If Time'
  if (score >= 60) return 'Apply Eventually: Backup Lane'
  return 'Skip'
}
for (const r of rows) {
  r.final_score = Math.round(
    r.desire_score * W.desire +
    r.market_perception_score * W.market +
    r.company_style_score * W.style +
    r.practicality_score * W.practicality
  )
  r.status = statusFor(r.final_score)
}
rows.sort((a, b) => b.final_score - a.final_score)

// ---- Build CSV (deterministic quoting) ----
function csvCell(v) {
  const s = (v === undefined || v === null) ? '' : String(v)
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}
const HEADER = 'Status?,Category,Company,Job Post Title + Link,Location?,Comp Range,lane,desire_score,market_perception_score,company_style_score,practicality_score,final_score,mission_fit_notes,scope_fit_notes,top_reasons,top_concerns,job_file'
const csvLines = [HEADER]
for (const r of rows) {
  csvLines.push([
    r.status, r.category, r.company, r.title_and_link, r.location, r.comp_range,
    r.lane, r.desire_score, r.market_perception_score, r.company_style_score, r.practicality_score,
    r.final_score, r.mission_fit_notes, r.scope_fit_notes,
    r.top_reasons, r.top_concerns, r.job_file,
  ].map(csvCell).join(','))
}
const csvContent = csvLines.join('\n') + '\n'

// ---- Build Markdown (sorted desc) ----
const mdParts = [`# Job Rankings\n\n${rows.length} jobs scored, highest priority first.\n`]
for (const r of rows) {
  mdParts.push(
`## ${r.final_score} — ${r.company}: ${r.title_and_link.split(' | ')[0]}

- **Status:** ${r.status}
- **Category:** ${r.category}  |  **Lane:** ${r.lane}
- **Location:** ${r.location}  |  **Comp:** ${r.comp_range}
- **Scores:** Desire ${r.desire_score} / Market ${r.market_perception_score} / Style ${r.company_style_score} / Practicality ${r.practicality_score} → **Final ${r.final_score}**
- **Mission fit:** ${r.mission_fit_notes}
- **Scope fit:** ${r.scope_fit_notes}
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

// ---- Phase 3: write the two files ----
phase('Assemble')
const WRITE_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['wrote'],
  properties: { wrote: { type: 'array', items: { type: 'string' } } },
}
await agent(
  `Write these two files EXACTLY as given, overwriting if they exist. Do not modify the content.

=== FILE 1: ${csvPath} ===
${csvContent}
=== END FILE 1 ===

=== FILE 2: ${mdPath} ===
${mdContent}
=== END FILE 2 ===

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

PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"; "$PY" 03-VETTING/make_rankings_xlsx.py "${csvPath}" "${xlsxPath}"

Do not edit the script. Return ok:true if it printed a "Wrote ..." line with no Python traceback; otherwise ok:false with the error text in message.`,
  { phase: 'Assemble', model: 'haiku', schema: XLSX_SCHEMA, label: 'build xlsx' }
)

return {
  folder: discovery.root,
  jobs_scored: rows.length,
  csv: csvPath,
  markdown: mdPath,
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
