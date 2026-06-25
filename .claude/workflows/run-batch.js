export const meta = {
  name: 'run-batch',
  description: 'Front door for a job batch: always vet + rank; OPTIONALLY continue into tailoring resumes for the top N jobs (sequentially, highest first). Vet-only is the default.',
  whenToUse: 'Run a vetting batch. Pass {folder} to vet only, or {folder, tailor: true, topN: 3} to also prepare resumes for the top jobs. `folder` is the review batch root, e.g. "__READY TO REVIEW/06-02-26".',
  phases: [
    { title: 'Vet', detail: 'score + rank the batch into "1 - Rankings/" (delegates to vet-jobs)' },
    { title: 'Tailor', detail: 'optional: prepare resume drafts into "2 - Tailored Resumes/", one at a time' },
  ],
}

// ---- Inputs ----
// Named-workflow invocation can deliver `args` as a JSON string; parse it back to a value first.
let A = args
if (typeof A === 'string') { try { A = JSON.parse(A) } catch (_) { /* leave as raw string */ } }
const FOLDER = (A && typeof A === 'object' && A.folder) ? A.folder : A
const TAILOR = !!(A && typeof A === 'object' && A.tailor)
const TOP_N = (A && typeof A === 'object' && Number.isInteger(A.topN)) ? A.topN : 3
// Default sequential ("one then the next"); set tailorParallel: true for overnight speed.
const TAILOR_PARALLEL = !!(A && typeof A === 'object' && A.tailorParallel)
if (!FOLDER || typeof FOLDER !== 'string') {
  throw new Error('Pass {folder} (vet only) or {folder, tailor: true, topN: 3} (vet + tailor top N). `folder` is the review batch root, e.g. "__READY TO REVIEW/06-02-26".')
}

// ---- Resolve the batch layout ----
// Every file a run produces lives under __READY TO REVIEW/<batch>/ in three tiers:
//   1 - Rankings/                    vet-jobs writes the CSV/MD/XLSX here
//   2 - Tailored Resumes/            one folder per tailored job
//   3 - Source Material/All Job Posts (full text)/   the fetched job .txt files
// `folder` may be the batch root itself OR the source subfolder — normalize to both. Nothing is
// moved after the fact: vetting writes rankings straight into tier 1, tailoring into tier 2.
const SRC_SUB = '3 - Source Material/All Job Posts (full text)'
const f = FOLDER.replace(/\/+$/, '')
const REVIEW_ROOT = f.includes('All Job Posts (full text)') ? f.split('/3 - Source Material/')[0] : f
const SOURCE = f.includes('All Job Posts (full text)') ? f : `${REVIEW_ROOT}/${SRC_SUB}`
const BATCH = REVIEW_ROOT.replace(/\/+$/, '').split('/').pop()
const RANKINGS_DIR = `${REVIEW_ROOT}/1 - Rankings`
const RESUMES_DIR = `${REVIEW_ROOT}/2 - Tailored Resumes`

// ---- Phase 1: vet (always) — rankings land in "1 - Rankings/", named after the batch ----
phase('Vet')
const vet = await workflow('vet-jobs', { folder: SOURCE, outDir: RANKINGS_DIR, batchName: BATCH })
if (!vet || vet.error || !Array.isArray(vet.ranked) || vet.ranked.length === 0) {
  return { stopped_after: 'vet', vet }
}

// ---- If tailoring is off, stop here so the candidate reviews and picks ----
if (!TAILOR) {
  log(`Vetting done — ${vet.jobs_scored} jobs ranked into "${RANKINGS_DIR}". Tailoring OFF.`)
  return {
    mode: 'vet-only',
    review_folder: REVIEW_ROOT,
    jobs_scored: vet.jobs_scored,
    csv: vet.csv,
    markdown: vet.markdown,
    xlsx: vet.xlsx,
    top: vet.top,
    note: `Vet-only run. Rankings are in "${RANKINGS_DIR}". To prepare resumes, pick jobs and run "tailor-jobs", or re-run with tailor: true.`,
  }
}

// ---- Phase 2: tailor the top N (sequential, highest first) ----
// Skip anything the rubric flagged as "Skip" — don't waste a tailor pass on a reject.
phase('Tailor')
const picks = vet.ranked.filter((r) => r.status !== 'Skip').slice(0, TOP_N)
if (picks.length === 0) {
  log('No top jobs above the Skip threshold — nothing to tailor.')
  return { mode: 'vet+tailor', review_folder: REVIEW_ROOT, jobs_scored: vet.jobs_scored, csv: vet.csv, markdown: vet.markdown, xlsx: vet.xlsx, tailored: [] }
}
if (picks.length < TOP_N) {
  log(`Only ${picks.length} of the top ${TOP_N} are above the Skip threshold — tailoring those.`)
}

const CONFIRM_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['job_folder', 'output_file', 'recommended_base', 'open_questions'],
  properties: {
    job_folder: { type: 'string' },
    output_file: { type: 'string' },
    recommended_base: { type: 'string' },
    open_questions: { type: 'integer', description: 'count of items in the Questions for the candidate section' },
  },
}

const tailorOne = (r, i) => agent(
  `Tailor a resume for ONE job, in autonomous mode.

Job description file (read this exact file): ${r.abs_path}
Company: ${r.company}
Role/title: ${r.title_and_link}
It ranked #${i + 1} this batch with a final score of ${r.final_score} (${r.status}).

Create the destination job folder INSIDE "${RESUMES_DIR}" using the naming convention
"Company - Role" (NO date — the parent batch folder is already dated; abbreviate long titles sensibly, e.g. Senior -> Sr,
Vice President -> VP). Use mkdir -p and quote paths since they contain spaces. Copy the job file in,
and write the output file ("application_resume_output - [Company] - [Role].md") there per your spec,
with the "Questions for the candidate" section at the top. Do not ask questions — defer them to that section.`,
  { agentType: 'job-applier', model: 'sonnet', phase: 'Tailor', schema: CONFIRM_SCHEMA, label: r.company }
).then((res) => (res ? { rank: i + 1, ...r, ...res } : null))

let tailored
if (TAILOR_PARALLEL) {
  log(`Tailoring ${picks.length} jobs in parallel`)
  tailored = (await parallel(picks.map((r, i) => () => tailorOne(r, i)))).filter(Boolean)
} else {
  tailored = []
  for (let i = 0; i < picks.length; i++) {
    log(`Tailoring ${i + 1}/${picks.length}: ${picks[i].company} (rank #${i + 1}, score ${picks[i].final_score})`)
    const res = await tailorOne(picks[i], i)
    if (res) tailored.push(res)
  }
}

return {
  mode: 'vet+tailor',
  review_folder: REVIEW_ROOT,
  jobs_scored: vet.jobs_scored,
  csv: vet.csv,
  markdown: vet.markdown,
  xlsx: vet.xlsx,
  tailored,
  note: `Prepared ${tailored.length} resume draft(s). Everything is in "${REVIEW_ROOT}" — open "1 - Rankings", then each folder in "2 - Tailored Resumes" (start with the "Questions for the candidate" section).`,
}
