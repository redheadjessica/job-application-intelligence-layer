export const meta = {
  name: 'run-batch',
  description: 'Front door for a job batch: always vet + rank; OPTIONALLY continue into tailoring resumes for the top N jobs (sequentially, highest first). Vet-only is the default.',
  whenToUse: 'Run a vetting batch. Pass {folder} to vet only, or {folder, tailor: true, topN: 3} to also prepare resumes for the top jobs. `folder` is the review batch root, e.g. "__READY_TO_REVIEW__PRIVATE_GITIGNORED/06-02-26".',
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
  throw new Error('Pass {folder} (vet only) or {folder, tailor: true, topN: 3} (vet + tailor top N). `folder` is the review batch root, e.g. "__READY_TO_REVIEW__PRIVATE_GITIGNORED/06-02-26".')
}

// ---- Resolve the batch layout ----
// Every file a run produces lives under __READY_TO_REVIEW__PRIVATE_GITIGNORED/<batch>/ in three tiers:
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
// (Tailored resumes land in "${REVIEW_ROOT}/2 - Tailored Resumes"; tailor-jobs computes that path
// itself from each job's batch, so run-batch no longer needs to name it here.)

// ---- Phase 1: vet (always) — rankings land in "1 - Rankings/", named after the batch ----
phase('Vet')
// Delegate to vet-jobs by scriptPath, NOT by name: the workflow-name registry is populated from
// scripts that PARSE at scan time and is cached per session, so vet-jobs can silently drop out of it
// (it did, after an earlier parse error) and never re-register mid-session. scriptPath resolves by
// FILE and does not depend on the registry, so the production path is deterministic across sessions.
// vet-jobs now scores Profile Fit INLINE (no nested child workflow), so this stays within the
// one-level nesting limit: run-batch -> vet-jobs, and nothing deeper.
const vet = await workflow({ scriptPath: '.claude/workflows/vet-jobs.js' }, { folder: SOURCE, outDir: RANKINGS_DIR, batchName: BATCH })
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
// Skip the lowest band ("Apply Eventually: Or Skip It", score < 60) — don't waste a tailor pass on it.
phase('Tailor')
const picks = vet.ranked.filter((r) => r.status !== 'Apply Eventually: Or Skip It').slice(0, TOP_N)
if (picks.length === 0) {
  log('No top jobs above the Skip threshold — nothing to tailor.')
  return { mode: 'vet+tailor', review_folder: REVIEW_ROOT, jobs_scored: vet.jobs_scored, csv: vet.csv, markdown: vet.markdown, xlsx: vet.xlsx, tailored: [] }
}
if (picks.length < TOP_N) {
  log(`Only ${picks.length} of the top ${TOP_N} are above the Skip threshold — tailoring those.`)
}

// Delegate the whole tailor pass to tailor-jobs, rather than tailoring inline here. Two reasons:
//  1. tailor-jobs owns the Record phase that writes each job's chosen base AND its resume-comparison
//     block (Base/Improved Resume Score, delta, Why It Improves) back into "1 - Rankings/" via
//     update_rankings_row.py. run-batch's old inline loop had NONE of that — it didn't even ask the
//     agent for the comparison scores — so the front-door vet+tailor flow left all six of those
//     tracker columns blank while the hand-picked tailor-jobs flow filled them. Collapsing to ONE
//     tailoring path makes the rankings writeback happen at the end of EVERY tailoring run, for all
//     users, without prompting — and structurally prevents that drift from ever recurring.
//  2. tailor-jobs names each folder from the shared canonicalizer (norm_contracts --application-name),
//     the same source of truth vetting uses, instead of an ad-hoc "Company - Role" abbreviation.
// One level of nesting only (run-batch -> tailor-jobs); tailor-jobs uses agent() and never calls
// workflow(), so this stays within the engine's one-level limit, exactly like run-batch -> vet-jobs.
const jobs = picks.map((r) => ({ abs_path: r.abs_path, company: r.company, title_and_link: r.title_and_link }))
const tj = await workflow({ scriptPath: '.claude/workflows/tailor-jobs.js' }, { jobs, parallel: TAILOR_PARALLEL })
const tailored = (tj && Array.isArray(tj.tailored)) ? tj.tailored : []

return {
  mode: 'vet+tailor',
  review_folder: REVIEW_ROOT,
  jobs_scored: vet.jobs_scored,
  csv: vet.csv,
  markdown: vet.markdown,
  xlsx: vet.xlsx,
  tailored,
  // Surface tailor-jobs' own writeback signals so a misrouted batch or an unmatched rankings row is
  // never silent here either.
  table: tj && tj.table,
  warnings: tj && tj.warnings,
  record_summary: tj && tj.record_summary,
  note: `${(tj && tj.warnings && tj.warnings.length) ? '⚠️ ' + tj.warnings.join(' ') + '\n\n' : ''}Prepared ${tailored.length} resume draft(s). Everything is in "${REVIEW_ROOT}" — open "1 - Rankings", then each folder in "2 - Tailored Resumes" (start with the "1. Decisions Needed" section). Each tailored job's chosen base and its resume-comparison block (Base/Improved Resume Score, delta, Why It Improves) were written back into "1 - Rankings/". Copy/paste table for your tracker is in the "table" field.`,
}
