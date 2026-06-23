export const meta = {
  name: 'tailor-jobs',
  description: 'Prepare resume drafts for a hand-picked set of jobs (sequential, in the order given). Use after a vet-only run when the candidate has chosen exactly which jobs to pursue.',
  whenToUse: 'Pass {jobs: ["path/to/jobA.txt", "path/to/jobB.txt"]} — the specific job files to tailor.',
  phases: [{ title: 'Tailor', detail: 'one resume draft per chosen job, in order' }],
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

// Consolidated review home: __READY TO REVIEW/<batch>/. Derive <batch> from each job file's
// parent folder (e.g. vetting/06-02-26/foo.txt -> 06-02-26) so hand-picked jobs land alongside
// their batch. Falls back to "manual" if the path has no recognizable parent.
function batchOf(p) {
  const parts = String(p || '').replace(/\/+$/, '').split('/')
  // Job files now also live under __READY TO REVIEW/<batch>/All Job Posts (full text)/foo.txt.
  // In that case the batch is the segment right after "__READY TO REVIEW", not the immediate
  // parent folder (which would be the "All Job Posts (full text)" subfolder).
  const idx = parts.indexOf('__READY TO REVIEW')
  if (idx >= 0 && parts.length > idx + 1) return parts[idx + 1]
  return parts.length >= 2 ? parts[parts.length - 2] : 'manual'
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
  const resumesDir = `__READY TO REVIEW/${batchOf(p.abs_path)}/2 - Tailored Resumes`
  const res = await agent(
    `Tailor a resume for ONE job, in autonomous mode.

Job description file (read this exact file): ${p.abs_path}
${p.company ? `Company: ${p.company}\n` : ''}${p.title_and_link ? `Role/title: ${p.title_and_link}\n` : ''}
Create the destination job folder INSIDE "${resumesDir}" using the naming convention
"Company - Role" (NO date — the parent batch folder is already dated; abbreviate Product Manager -> PM,
Vice President -> VP). Use mkdir -p and quote paths since they contain spaces. Copy the job file in,
and write the output file ("application_resume_output - [Company] - [Role].md") there per your spec,
with the "Questions for the candidate" section at the top. Do not ask questions — defer them to that section.`,
    { agentType: 'job-applier', model: 'sonnet', phase: 'Tailor', schema: CONFIRM_SCHEMA, label: who }
  )
  if (res) tailored.push({ order: i + 1, ...p, ...res })
}

return {
  tailored,
  note: `Prepared ${tailored.length} resume draft(s) in __READY TO REVIEW/. Open each job folder's "application_resume_output - [Company] - [Role].md", starting with the "Questions for the candidate" section.`,
}
