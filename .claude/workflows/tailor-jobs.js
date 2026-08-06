export const meta = {
  name: 'tailor-jobs',
  description: 'Prepare resume drafts for a hand-picked set of jobs (sequential, in the order given). Use after a vet-only run when the candidate has chosen exactly which jobs to pursue.',
  whenToUse: 'Pass {jobs: ["path/to/jobA.txt", "path/to/jobB.txt"]} — the specific job files to tailor.',
  phases: [
    { title: 'Tailor', detail: 'one resume draft per chosen job, in order' },
    { title: 'Record', detail: 'write each chosen base back into the batch rankings' },
  ],
}

// ---- Base-name terseness (mirrors update_rankings_row.py's terse_base — keep in sync) ----
// Used for the copy/paste table below, independent of whether the Record-phase writeback found a
// matching rankings row. Jessica's house style: "Company — Role (M/D/YY)", no trailing prose.
const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 }
function terseBase(raw) {
  let s = String(raw || '').trim().replace(/\*\*/g, '')
  s = s.replace(/^\s*[-*•]\s+/, '')
  s = s.replace(/^\s*(?:primary|chosen|recommended|selected)\s+base\s*(?:\(merge\))?\s*:\s*/i, '')
  s = s.replace(/^\s*base\s+(?:chosen|used|actually used)\s*:\s*/i, '')
  // Collapse a date-paren carrying extra words: "(7/1/26 finalized submission)" -> "(7/1/26)"
  s = s.replace(/\((\d{1,2}\/\d{1,2}\/\d{2}|\d{1,2}\/\d{2})[^)]*\)/, '($1)')
  const dateEnd = /^(.*?\((?:\d{1,2}\/\d{1,2}\/\d{2}|\d{1,2}\/\d{2}|[A-Z][a-z]{2,8}\s+\d{4})\))/.exec(s)
  if (dateEnd) {
    s = dateEnd[1]
  } else {
    const bare = /\d{1,2}\/\d{1,2}\/\d{2}|\d{1,2}\/\d{2}/.exec(s)
    s = bare ? s.slice(0, bare.index + bare[0].length)
      : s.split(/(?:,\s*(?:adapted|merged|chassis|retitled|copied|from the)|\.\s|\s+chassis\b|\s+—\s*see\b)/i)[0]
  }
  s = s.trim().replace(/[.,]+$/, '').trim()
  s = s.replace(/\(([A-Z][a-z]{2,8})\s+(\d{4})\)/, (m, mon, yr) => {
    const n = MONTHS[mon.toLowerCase().slice(0, 3)]
    return n ? `(${n}/${yr.slice(-2)})` : m
  })
  return s.replace('Professional Services', 'Prof. Services')
}

// Named-workflow invocation can deliver `args` as a JSON string; parse it back to a value first.
let A = args
if (typeof A === 'string') { try { A = JSON.parse(A) } catch (_) { /* leave as raw string */ } }

// Accept {jobs: [...]} or a bare array. Each item may be a path string or {abs_path, company}.
const raw = (A && typeof A === 'object' && Array.isArray(A.jobs)) ? A.jobs
  : (Array.isArray(A) ? A : null)
if (!raw || raw.length === 0) {
  throw new Error('Pass {jobs: ["path/to/jobA.txt", ...]} — the specific job files to tailor.')
}
const picks = raw.map((j) => (typeof j === 'string' ? { abs_path: j } : j))
// Sequential by default (in the order given). `parallel` (or `tailorParallel`) fans the tailoring
// agents out at once — used by run-batch's overnight mode, which delegates the whole tailor+Record
// pass here so there is exactly ONE tailoring path and the rankings writeback can never drift back
// out of the front door again.
const PARALLEL = !!(A && typeof A === 'object' && (A.parallel || A.tailorParallel))

// Consolidated review home: __READY_TO_REVIEW__PRIVATE_GITIGNORED/<batch>/. Derive <batch> from each job file's
// parent folder (e.g. __READY_TO_REVIEW__PRIVATE_GITIGNORED/06-02-26/foo.txt -> 06-02-26) so hand-picked jobs land alongside
// their batch. Falls back to "manual" if the path has no recognizable parent.
// A job batch is a date-shaped folder: exactly `MM-DD-YY`, or `MM-DD-YY - <label>` when the path
// gives STRUCTURAL evidence that it really is a batch (the job file sits under that folder's
// "3 - Source Material/"). Review folders — "06-02-26 - Intake Review", "… - Source Update Review",
// "… - Formatting Review" — are still excluded: they never contain source material, and the
// "… Review" suffix is rejected outright as a second guard.
//
// Why this loosened (2026-07-30): a real batch named "07-30-26 - Unified 55-Job Tracker" fell
// through to "manual/", so tailored folders landed outside the batch AND the rankings writeback
// found no rankings file and wrote nothing — while the workflow still reported success. The strict
// name test was excluding review folders by NAME when the thing that actually distinguishes them
// is STRUCTURE, which the path already carries.
const DATE_PREFIX_RE = /^\d{2}-\d{2}-\d{2}(?:\s+-\s+.+)?$/
const REVIEW_SUFFIX_RE = /\breview\s*$/i
const isBatchName = (s) => /^\d{2}-\d{2}-\d{2}$/.test(s)
const isDatedBatchName = (s) => DATE_PREFIX_RE.test(String(s || '')) && !REVIEW_SUFFIX_RE.test(String(s || ''))
const SOURCE_DIR = '3 - Source Material'
function batchOf(p) {
  const parts = String(p || '').replace(/\/+$/, '').split('/')
  const idx = parts.indexOf('__READY_TO_REVIEW__PRIVATE_GITIGNORED')
  if (idx >= 0 && parts.length > idx + 1) {
    const candidate = parts[idx + 1]
    // Exactly date-shaped: always a batch (unchanged behavior).
    if (isBatchName(candidate)) return candidate
    // Date-prefixed with a label: a batch when the path proves it holds source material.
    if (isDatedBatchName(candidate) && parts[idx + 2] === SOURCE_DIR) return candidate
  }
  const parent = parts.length >= 2 ? parts[parts.length - 2] : ''
  if (isBatchName(parent)) return parent
  // A job file directly inside a labelled batch folder still resolves to it.
  const grand = parts.length >= 3 ? parts[parts.length - 3] : ''
  if (parts[parts.length - 2] === SOURCE_DIR && isDatedBatchName(grand)) return grand
  return 'manual'
}

const CONFIRM_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['job_folder', 'output_file', 'company', 'role', 'recommended_base', 'open_questions'],
  properties: {
    job_folder: { type: 'string' },
    output_file: { type: 'string' },
    company: { type: 'string', description: 'the hiring company, exactly as used in the canonical folder name' },
    role: { type: 'string', description: 'the CANONICAL role — the part of the canonicalizer output after "Company - "' },
    recommended_base: { type: 'string' },
    open_questions: { type: 'integer' },
    // The resume-comparison pass. Omitted entirely when the base artifact could not be read —
    // a blank block in the tracker is the honest way to say "not scored", and an estimate made
    // from the resume index's prose preview would be indistinguishable from a real measurement.
    base_resume_score: { type: 'integer', description: '0-100, multiple of 5, from the ACTUAL base file' },
    improved_resume_score: { type: 'integer', description: '0-100, multiple of 5, never below base' },
    why_it_improves: { type: 'string', description: 'one or two sentences naming the changes behind the delta' },
    base_artifact_status: { type: 'string', description: 'ok | no-readable-pdf | not-found' },
  },
}

// Single source of truth for tailored-application names: the shared canonicalizer CLI.
// Workflow scripts can't run shell directly, so the agent is told to run this exact
// command FIRST and use its output verbatim as the folder name (never derive/abbreviate
// its own). When the pick carries company/title from the rankings, the command arrives
// fully filled-in; otherwise the agent fills in company/role from the job post.
const shq = (s) => `'${String(s).replace(/'/g, `'\\''`)}'`   // safe single-quoted shell arg
const NAME_CLI = 'PY=".venv/bin/python3"; [ -x "$PY" ] || PY="python3"; "$PY" ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/norm_contracts.py --application-name'
function nameCmdFor(p) {
  const roleGuess = p.title_and_link ? String(p.title_and_link).split(' | ')[0].trim() : ''
  return (p.company && roleGuess)
    ? `${NAME_CLI} --company ${shq(p.company)} --role ${shq(roleGuess)}`
    : `${NAME_CLI} --company '<Company from the job post>' --role '<Role/title from the job post>'`
}

phase('Tailor')
const tailorOne = async (p, i) => {
  const who = p.company || p.abs_path
  log(`Tailoring ${i + 1}/${picks.length}: ${who}`)
  const resumesDir = `__READY_TO_REVIEW__PRIVATE_GITIGNORED/${batchOf(p.abs_path)}/2 - Tailored Resumes`
  const res = await agent(
    `Tailor a resume for ONE job, in autonomous mode.

Job description file (read this exact file): ${p.abs_path}
${p.company ? `Company: ${p.company}\n` : ''}${p.title_and_link ? `Role/title: ${p.title_and_link}\n` : ''}
Create the destination job folder INSIDE "${resumesDir}". The folder name must be EXACTLY the output
of the shared canonicalizer — run this command FIRST and use its printed string verbatim (NO date —
the parent batch folder is already dated; never invent your own abbreviations):

${nameCmdFor(p)}

Use mkdir -p and quote paths since they contain spaces. Copy the job file in, and write the output
file ("application_resume_output - <canonical name>.md") there per your spec, with the "Questions
for the candidate" section at the top. Do not ask questions — defer them to that section.
In your structured return, "company" and "role" are the canonical values: role = the part of the
canonicalizer output after "<Company> - ".

REBUILD-ON-STALE: if an "application_resume_output*.md" ALREADY EXISTS in that folder, treat it as
STALE — the candidate's canon (profile, boundary rules, experience bank, summary/skills sources,
resume index) has very likely been updated since it was written. You are being re-run precisely to
re-incorporate the current canon. Do NOT read the old draft and conclude it "holds up" / is "good
enough" and skip the rewrite. Rebuild the analysis fresh from the current canon and OVERWRITE the
file. The finished .md must reflect every current credential, confirmed gap, and guardrail —
re-derive, don't ratify the old draft.`,
    { agentType: 'job-applier', model: 'sonnet', phase: 'Tailor', schema: CONFIRM_SCHEMA, label: who }
  )
  return res ? { order: i + 1, ...p, ...res } : null
}

let tailored
if (PARALLEL) {
  log(`Tailoring ${picks.length} job(s) in parallel`)
  tailored = (await parallel(picks.map((p, i) => () => tailorOne(p, i)))).filter(Boolean)
} else {
  tailored = []
  for (let i = 0; i < picks.length; i++) {
    const res = await tailorOne(picks[i], i)
    if (res) tailored.push(res)
  }
}

// ---- Write each chosen base back into the batch's rankings (added 7/16/26) ----
// The agent has always returned `recommended_base`; until now it was discarded, so the tracker's
// "Base Resume Used" column was blank in every batch ever produced and had to be reconstructed by
// hand from the per-job .md files. Match by URL first (the same posting gets re-fetched under
// different filenames across batches), falling back to the job filename.
const jobFileOf = (p) => String(p || '').split('/').pop()
const urlOf = (t) => { const m = /https?:\/\/\S+/.exec(String(t || '')); return m ? m[0] : null }

// A complete resume-comparison block. Checked here rather than trusted from the agent because a
// partial block is worse than none: written into the tracker it reads as a finished comparison
// whose improvement happened to be zero.
const hasComparison = (t) => (
  Number.isInteger(t.base_resume_score) && Number.isInteger(t.improved_resume_score)
  && String(t.why_it_improves || '').trim() !== ''
)

// A job whose batch could not be resolved has nowhere for the writeback to land. That used to
// be invisible: the workflow reported success while the Tailored?/Cover Letter columns silently
// stayed empty. Same failure class as a manifest wipe — surface it in the RESULT.
const misrouted = tailored.filter((t) => batchOf(t.abs_path) === 'manual')
const warnings = misrouted.length
  ? [`${misrouted.length} tailored job(s) could not be matched to a batch folder, so their `
    + `"Tailored? (Base Resume)" / "Cover Letter Drafted?" cells were NOT updated: `
    + misrouted.map((t) => jobFileOf(t.abs_path)).join(', ')
    + `. Their drafts are in __READY_TO_REVIEW__PRIVATE_GITIGNORED/manual/2 - Tailored Resumes/. `
    + `A batch folder must be named MM-DD-YY (optionally "MM-DD-YY - <label>") and the job file `
    + `must live under its "3 - Source Material/".`]
  : []

let recordSummary = null
if (tailored.length) {
  phase('Record')
  const cmds = tailored.filter((t) => t.recommended_base).map((t) => {
    const batchDir = `__READY_TO_REVIEW__PRIVATE_GITIGNORED/${batchOf(t.abs_path)}`
    const url = urlOf(t.title_and_link)
    return [
      `PY=".venv/bin/python3"; [ -x "$PY" ] || PY="python3"; "$PY"`,
      `ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/update_rankings_row.py`,
      `--batch ${shq(batchDir)}`,
      `--job-file ${shq(jobFileOf(t.abs_path))}`,
      url ? `--url ${shq(url)}` : '',
      `--base ${shq(t.recommended_base)}`,
      // All three or none — update_rankings_row.py rejects a half-written block outright, and
      // derives the delta itself so the stored value can never disagree with its operands.
      hasComparison(t) ? `--base-score ${t.base_resume_score}` : '',
      hasComparison(t) ? `--improved-score ${t.improved_resume_score}` : '',
      hasComparison(t) ? `--why ${shq(t.why_it_improves)}` : '',
    ].filter(Boolean).join(' ')
  })
  if (cmds.length) {
    recordSummary = await agent(
      `Record each tailored job's chosen resume base back into its batch rankings.

Run these EXACT shell commands from the project root, in order, and report each one's output verbatim:

${cmds.join('\n')}

Each prints either "Updated ..." (success) or a line starting with "WARNING: no rankings row matched".
Do NOT treat a WARNING as fatal and do NOT retry or "fix" it — just report it. Return a short summary:
how many updated, and the full text of any WARNING lines (both "no rankings row matched" and
"no '1 - Rankings/' folder" are WARNINGs that must be reported verbatim, never summarized away).`,
      { phase: 'Record', model: 'haiku', label: 'record bases in rankings' }
    )
  }
}

// ---- Always end with a paste-ready table (added 7/17/26) ----
// The Record-phase writeback only lands when the job's batch has a rankings file to update — a
// backlog job tailored outside any current batch (e.g. into "manual/") has nowhere for that to
// land, and the base/cover-letter data would otherwise only exist buried in each job's .md file.
// This table is unconditional: it's the thing Jessica actually copies into her Google Sheet, and
// it must show up every run regardless of whether the rankings writeback found a home.
// Prefer the agent's returned canonical company/role; folder-name splitting is a
// last-resort fallback only (it breaks on roles containing " - ").
const roleOf = (t) => t.role || (t.title_and_link || '').split(' | ')[0] || (t.job_folder || '').split('/').pop().split(' - ').slice(1).join(' - ') || ''
const tableRows = tailored.map((t) => ({
  company: t.company || (t.job_folder || '').split('/').pop().split(' - ')[0] || '',
  role: roleOf(t),
  base: t.recommended_base ? terseBase(t.recommended_base) : '',
}))
const table = [
  '| Company | Role | Base Resume Used |',
  '|---|---|---|',
  ...tableRows.map((r) => `| ${r.company} | ${r.role} | ${r.base} |`),
].join('\n')

return {
  tailored,
  table,
  // Loud, never silent: a writeback that found no home is reported in the result itself,
  // not left for the user to discover as empty tracker cells weeks later.
  warnings,
  record_summary: recordSummary,
  note: `${warnings.length ? '⚠️ ' + warnings.join(' ') + '\n\n' : ''}Prepared ${tailored.length} resume draft(s) in __READY_TO_REVIEW__PRIVATE_GITIGNORED/. Open each job folder's "application_resume_output - [Company] - [Role].md", starting with the "Questions for the candidate" section. Each job's chosen base was also written back into its batch's "Tailored? (Base Resume)" column where a rankings file exists for it. Copy/paste table for your tracker is in the "table" field (no Cover Letter column — tailor-jobs never generates letters; run the cover-letter workflow separately if you want one, which adds its own paste table for that column).`,
}
