export const meta = {
  name: 'tailor-jobs',
  description: 'Prepare resume drafts for a hand-picked set of jobs (sequential, in the order given). Use after a vet-only run when the candidate has chosen exactly which jobs to pursue.',
  whenToUse: 'Pass {jobs: ["path/to/jobA.txt", "path/to/jobB.txt"]} — the specific job files to tailor.',
  phases: [
    { title: 'Tailor', detail: 'one resume draft per chosen job, in order' },
    { title: 'Record', detail: 'write each chosen base back into the batch rankings' },
  ],
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

// Consolidated review home: __READY_TO_REVIEW__PRIVATE_GITIGNORED/<batch>/. Derive <batch> from each job file's
// parent folder (e.g. __READY_TO_REVIEW__PRIVATE_GITIGNORED/06-02-26/foo.txt -> 06-02-26) so hand-picked jobs land alongside
// their batch. Falls back to "manual" if the path has no recognizable parent.
// A job batch is ONLY a date-shaped folder (MM-DD-YY). Non-batch review folders under
// __READY_TO_REVIEW__PRIVATE_GITIGNORED (e.g. "06-02-26 - Intake Review", "06-02-26 - Source Update Review")
// must never be treated as a batch.
const isBatchName = (s) => /^\d{2}-\d{2}-\d{2}$/.test(s)
function batchOf(p) {
  const parts = String(p || '').replace(/\/+$/, '').split('/')
  // Job files live under __READY_TO_REVIEW__PRIVATE_GITIGNORED/<batch>/.../foo.txt — the batch is the segment
  // right after "__READY_TO_REVIEW__PRIVATE_GITIGNORED", but only if it is date-shaped.
  const idx = parts.indexOf('__READY_TO_REVIEW__PRIVATE_GITIGNORED')
  if (idx >= 0 && parts.length > idx + 1 && isBatchName(parts[idx + 1])) return parts[idx + 1]
  // Fallback: the immediate parent folder, only if it is itself date-shaped; else "manual".
  const parent = parts.length >= 2 ? parts[parts.length - 2] : ''
  return isBatchName(parent) ? parent : 'manual'
}

const CONFIRM_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['job_folder', 'output_file', 'recommended_base', 'open_questions'],
  properties: {
    job_folder: { type: 'string' },
    output_file: { type: 'string' },
    recommended_base: { type: 'string' },
    open_questions: { type: 'integer' },
  },
}

phase('Tailor')
const tailored = []
for (let i = 0; i < picks.length; i++) {
  const p = picks[i]
  const who = p.company || p.abs_path
  log(`Tailoring ${i + 1}/${picks.length}: ${who}`)
  const resumesDir = `__READY_TO_REVIEW__PRIVATE_GITIGNORED/${batchOf(p.abs_path)}/2 - Tailored Resumes`
  const res = await agent(
    `Tailor a resume for ONE job, in autonomous mode.

Job description file (read this exact file): ${p.abs_path}
${p.company ? `Company: ${p.company}\n` : ''}${p.title_and_link ? `Role/title: ${p.title_and_link}\n` : ''}
Create the destination job folder INSIDE "${resumesDir}" using the naming convention
"Company - Role" (NO date — the parent batch folder is already dated; abbreviate long titles sensibly, e.g. Senior -> Sr,
Vice President -> VP). Use mkdir -p and quote paths since they contain spaces. Copy the job file in,
and write the output file ("application_resume_output - [Company] - [Role].md") there per your spec,
with the "Questions for the candidate" section at the top. Do not ask questions — defer them to that section.

REBUILD-ON-STALE: if an "application_resume_output*.md" ALREADY EXISTS in that folder, treat it as
STALE — the candidate's canon (profile, boundary rules, experience bank, summary/skills sources,
resume index) has very likely been updated since it was written. You are being re-run precisely to
re-incorporate the current canon. Do NOT read the old draft and conclude it "holds up" / is "good
enough" and skip the rewrite. Rebuild the analysis fresh from the current canon and OVERWRITE the
file. The finished .md must reflect every current credential, confirmed gap, and guardrail —
re-derive, don't ratify the old draft.`,
    { agentType: 'job-applier', model: 'sonnet', phase: 'Tailor', schema: CONFIRM_SCHEMA, label: who }
  )
  if (res) tailored.push({ order: i + 1, ...p, ...res })
}

// ---- Write each chosen base back into the batch's rankings (added 7/16/26) ----
// The agent has always returned `recommended_base`; until now it was discarded, so the tracker's
// "Base Resume Used" column was blank in every batch ever produced and had to be reconstructed by
// hand from the per-job .md files. Match by URL first (the same posting gets re-fetched under
// different filenames across batches), falling back to the job filename.
const jobFileOf = (p) => String(p || '').split('/').pop()
const urlOf = (t) => { const m = /https?:\/\/\S+/.exec(String(t || '')); return m ? m[0] : null }

if (tailored.length) {
  phase('Record')
  const shq = (s) => `'${String(s).replace(/'/g, `'\\''`)}'`   // safe single-quoted shell arg
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
    ].filter(Boolean).join(' ')
  })
  if (cmds.length) {
    await agent(
      `Record each tailored job's chosen resume base back into its batch rankings.

Run these EXACT shell commands from the project root, in order, and report each one's output verbatim:

${cmds.join('\n')}

Each prints either "Updated ..." (success) or a line starting with "WARNING: no rankings row matched".
Do NOT treat a WARNING as fatal and do NOT retry or "fix" it — just report it. Return a short summary:
how many updated, and the full text of any WARNING lines.`,
      { phase: 'Record', model: 'haiku', label: 'record bases in rankings' }
    )
  }
}

return {
  tailored,
  note: `Prepared ${tailored.length} resume draft(s) in __READY_TO_REVIEW__PRIVATE_GITIGNORED/. Open each job folder's "application_resume_output - [Company] - [Role].md", starting with the "Questions for the candidate" section. Each job's chosen base was also written back into its batch's "Base Resume Used" column.`,
}
