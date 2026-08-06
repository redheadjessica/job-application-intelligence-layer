export const meta = {
  name: 'cover-letter',
  description: 'Draft (or revise-with-feedback) -> lint -> dual eval (fit + voice) -> finalize (surgical revise + .docx + link QA + compact scorecard), for one or more jobs.',
  whenToUse: 'Pass {jobs: ["path/to/job.txt", ...]} (or {job: "path"}). Optional {out: "explicit output folder"} when a job folder already exists. Optional {feedback: "the candidate\'s targeted feedback on an EXISTING letter"} switches Stage 1 from draft-from-scratch to REVISE-WITH-FEEDBACK: the writer revises the most recent letter in the job folder (or {baseline: "path/to/final-vN.md"}) to address the feedback, then the same eval + finalize loop runs and versions the result (never overwriting the original). Requires the cover-letter instances (run /cover-letter-intake first).',
  phases: [
    { title: 'Draft', detail: 'writer agent, lint-gated' },
    { title: 'Evaluate', detail: 'fit + voice scores, adversarial, self-pushback' },
    { title: 'Finalize', detail: 'surgical fixes + anti-smoothing lint + .docx + link QA + packet' },
    { title: 'Record', detail: 'mark Cover Letter? = Y in the batch rankings' },
  ],
}

// Named-workflow invocation can deliver `args` as a JSON string; parse it back first.
let A = args
if (typeof A === 'string') { try { A = JSON.parse(A) } catch (_) { /* raw string = single job path */ } }

const jobList = (A && typeof A === 'object' && Array.isArray(A.jobs)) ? A.jobs
  : (A && typeof A === 'object' && A.job) ? [A.job]
  : (typeof A === 'string' && A.trim()) ? [A.trim()]
  : (Array.isArray(A) ? A : null)
if (!jobList || jobList.length === 0) {
  throw new Error('Pass {jobs: ["path/to/job.txt", ...]} or {job: "path/to/job.txt"}.')
}
const outOverride = (A && typeof A === 'object' && A.out) ? A.out : null
// REVISE-WITH-FEEDBACK mode: when the candidate gives targeted feedback on an existing letter,
// Stage 1 revises the latest letter instead of drafting from scratch. Everything downstream is unchanged.
const FEEDBACK = (A && typeof A === 'object' && typeof A.feedback === 'string' && A.feedback.trim()) ? A.feedback.trim() : null
const BASELINE = (A && typeof A === 'object' && A.baseline) ? A.baseline : null

// Derive the batch the same way tailor-jobs does, so letters land beside resume drafts.
function batchOf(p) {
  const parts = String(p || '').replace(/\/+$/, '').split('/')
  const idx = parts.indexOf('__READY_TO_REVIEW__PRIVATE_GITIGNORED')
  if (idx >= 0 && parts.length > idx + 1) return parts[idx + 1]
  return parts.length >= 2 ? parts[parts.length - 2] : 'manual'
}

const NO_WRAP = 'FORMATTING RULE for every file you write: never hard-wrap prose at a column width — one paragraph (or list item) = one line.'

const DRAFT_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['job_folder', 'draft_path', 'company', 'role', 'links_used', 'word_count', 'lint_errors', 'lint_warnings', 'open_questions'],
  properties: {
    job_folder: { type: 'string' },
    draft_path: { type: 'string' },
    company: { type: 'string' },
    role: { type: 'string' },
    links_used: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['anchor', 'url', 'why'], properties: { anchor: { type: 'string' }, url: { type: 'string' }, why: { type: 'string' } } } },
    word_count: { type: 'integer' },
    lint_errors: { type: 'integer' },
    lint_warnings: { type: 'array', items: { type: 'string' } },
    open_questions: { type: 'array', items: { type: 'string' } },
  },
}

const EVAL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['fit_score', 'voice_score', 'eval_path', 'must_fix', 'considerations', 'comparison_note'],
  properties: {
    fit_score: { type: 'integer', minimum: 1, maximum: 5 },
    voice_score: { type: 'integer', minimum: 1, maximum: 5 },
    eval_path: { type: 'string' },
    must_fix: { type: 'array', items: { type: 'string' } },
    considerations: { type: 'array', items: { type: 'string' } },
    comparison_note: { type: 'string' },
  },
}

const FINALIZE_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['final_md_path', 'docx_path', 'review_path', 'changes_applied', 'declined', 'lint_errors', 'link_qa', 'remaining_flags'],
  properties: {
    final_md_path: { type: 'string' },
    docx_path: { type: 'string' },
    review_path: { type: 'string' },
    changes_applied: { type: 'array', items: { type: 'string' } },
    declined: { type: 'array', items: { type: 'string' }, description: 'findings the writer disagreed with, and why (these go in the packet Questions)' },
    lint_errors: { type: 'integer' },
    link_qa: { type: 'string' },
    remaining_flags: { type: 'array', items: { type: 'string' } },
  },
}

// One job flows Draft -> Evaluate -> Finalize independently (no cross-job barriers).
const results = await pipeline(
  jobList,

  // ---- Stage 1: Draft (or Revise-with-feedback) ----
  async (jobPath) => {
    const destParent = outOverride || `__READY_TO_REVIEW__PRIVATE_GITIGNORED/${batchOf(jobPath)}/2 - Tailored Resumes`
    const locationInstr = outOverride
      ? `use this existing folder directly: "${outOverride}"`
      : `find or create the job folder inside "${destParent}". The folder name is the canonical "Company - Role" string — obtain it by running the shared canonicalizer FIRST with the company and role from the job post, and use its printed output verbatim (no date; never invent your own abbreviations):

PY=".venv/bin/python3"; [ -x "$PY" ] || PY="python3"; "$PY" ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/norm_contracts.py --application-name --company '<Company>' --role '<Role/title>'

If a folder with exactly that canonical name already exists there (the resume-tailoring step creates it with the same command), use it — do not create a second variant folder. mkdir -p with quoted paths.`

    const modeInstr = FEEDBACK
      ? `REVISE-WITH-FEEDBACK mode. The candidate has read an EXISTING cover letter for this job and given targeted feedback. Produce the next version that FULLY addresses the feedback while preserving what already works. Follow your spec (.claude/agents/cover-letter-writer.md — read the candidate's canon files FIRST; the cover-letter feedback-ledger's newest entries win, and today's entries were written to capture exactly this feedback). Respect every truth boundary in canon (e.g. no formal PM direct reports; never name a RIDG client or client industry; Ascend private-alpha guardrails).

The candidate's targeted feedback (this is FACT — apply it; her own words and rulings outrank any general guidance):
"""
${FEEDBACK}
"""

${BASELINE
        ? `The letter to revise is: "${BASELINE}". Read it in full first.`
        : `The letter to revise is whatever this prints — do NOT ls and guess, and do NOT assume a location (folders exist in several historical shapes):
    .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/job_folder_layout.py "<job folder>" --find latest-letter
It resolves the highest-numbered "final-v*.md", else "final.md", else the first draft. Read it in full before revising.`}

Revise so that you (a) do everything the feedback asks, (b) keep the structure, opener shape, bullets, closing, and inline links the candidate said she likes EXCEPT where the feedback changes them, and (c) surface any newly-relevant evidence the feedback points to — pull it from the experience bank / anecdote bank, never invent. Keep the letter one page.

⭐ HARD RULE — the candidate's OWN words are FACT (§0). When she hand-wrote the baseline, preserve her exact wording everywhere the feedback does not explicitly ask you to change it. Do NOT "improve", tighten, smooth, genericize, or reword any sentence she wrote and did not flag — verbatim preservation is the default, changes are the exception, and the exceptions are only the ones she named. If any of her wording raises a concern (a confidentiality wall, a truth boundary, a possible inaccuracy), KEEP HER WORDS VERBATIM and raise it as a question in the review packet — a concern about her text is a question to ask her, never a license to quietly rewrite it, and never grounds to "play it safe" by editing her word out. Silently altering a word she wrote herself is a failure, even when the replacement seems safer.

Get the directory to write into (create it if needed):
    .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/job_folder_layout.py "<job folder>" --write-dir cover-letter
Write your revised letter there as the next unused "draft-v<N>.md" (e.g. draft-v3.md if draft-v1.md and draft-v2.md exist). NEVER overwrite an existing draft or any final*.md. Run the lint gate on your new draft as your spec requires.`
      : `DRAFT mode. Write ONE cover letter per your spec (.claude/agents/cover-letter-writer.md rules apply — read the candidate's canon files first; feedback-ledger newest entries win).

Ask for the directory to write into, create it, and write your draft there as "draft-v1.md":
    .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/job_folder_layout.py "<job folder>" --write-dir cover-letter
Run the lint gate on it as your spec requires. Never compose that path yourself — the command already accounts for every historical folder shape.`

    const draft = await agent(
      `${modeInstr}

Job description file (read this exact file): ${jobPath}

Working location: ${locationInstr}

Always create/write inside the directory the --write-dir command prints (never at the job-folder top level, and never a path you composed yourself). ${NO_WRAP}

Return (structured): job_folder, draft_path (the file you just wrote), company, role, links_used [{anchor,url,why}], word_count, lint_errors (must be 0), lint_warnings [strings], open_questions [strings]. "company" and "role" must be the CANONICAL values from the canonicalizer output (role = the part after "<Company> - ") — they are interpolated verbatim into the .docx and packet filenames downstream.`,
      { agentType: 'cover-letter-writer', phase: 'Draft', schema: DRAFT_SCHEMA, label: `${FEEDBACK ? 'revise' : 'draft'}:${jobPath.split('/').pop()}` }
    )
    if (!draft) throw new Error(`${FEEDBACK ? 'revise' : 'draft'} agent failed for ${jobPath}`)
    if (draft.lint_errors > 0) log(`WARNING: ${FEEDBACK ? 'revised draft' : 'draft'} for ${draft.company} returned with ${draft.lint_errors} lint errors`)
    return { jobPath, draft }
  },

  // ---- Stage 2: Evaluate ----
  async ({ jobPath, draft }) => {
    const evaluation = await agent(
      `Evaluate ONE cover letter draft per PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/cover-letter/eval-rubric.md (read it first, follow it exactly — including any dose rules in the feedback ledger).

Draft: ${draft.draft_path}
Job description: ${jobPath}
Job folder (check for application_resume_output): ${draft.job_folder}

Write your evaluation to "eval-v1.md" (or the next unused "eval-v<N>.md") inside the directory printed by: .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/job_folder_layout.py "${draft.job_folder}" --write-dir cover-letter Keep it TERSE — max ~40 lines, findings only, no restating the letter. ${NO_WRAP}

Return (structured): fit_score, voice_score, eval_path, must_fix [strings, each citing the line], considerations [strings], comparison_note (one sentence vs the GOLD exemplar).`,
      { agentType: 'cover-letter-evaluator', phase: 'Evaluate', schema: EVAL_SCHEMA, label: `eval:${draft.company}` }
    )
    if (!evaluation) throw new Error(`evaluator failed for ${draft.company}`)
    log(`${draft.company}: fit ${evaluation.fit_score}/5, voice ${evaluation.voice_score}/5, ${evaluation.must_fix.length} must-fix`)
    return { jobPath, draft, evaluation }
  },

  // ---- Stage 3: Finalize (surgical revise if needed + docx + link QA + compact packet) ----
  async ({ jobPath, draft, evaluation }) => {
    const needsRevision = evaluation.must_fix.length > 0 || evaluation.fit_score < 4 || evaluation.voice_score < 4
    const pkg = await agent(
      `FINALIZE one cover letter. You are the writer agent (.claude/agents/cover-letter-writer.md — read the candidate's canon files first). ${NO_WRAP}

Draft: ${draft.draft_path}
Evaluation: ${evaluation.eval_path} (fit ${evaluation.fit_score}/5, voice ${evaluation.voice_score}/5, ${evaluation.must_fix.length} must-fix)
Job description: ${jobPath}
Job folder: ${draft.job_folder}

⚠️ NEVER OVERWRITE AN ORIGINAL (church-and-state, HARD RULE for every user — see formatting-spec.md).
FIRST, ask whether an immutable baseline already exists — never ls and judge for yourself, because the
answer decides whether you may write final.md at all:
    .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/job_folder_layout.py "${draft.job_folder}" --find coverletter-baseline
It prints the baseline's path if one exists (in ANY historical folder shape), or nothing if none does.
- If neither exists: this is the first letter for this job. Use the un-versioned target names below
  (final.md / the standard .docx name / the standard packet name).
- If EITHER exists: an immutable learning baseline is already here (reconcile diffs that ORIGINAL
  final.md/.docx against the PDF the candidate actually submits — overwriting it destroys that signal).
  You MUST NOT touch the existing final.md, its .docx, or its packet — wherever they live. Write THIS
  run's outputs to the next unused versioned names instead: "final-v2.md" (or -v3…) in the --write-dir
  directory, the .docx with " - v2" before the extension, and the packet with " - v2" before ".md".
  Leave every original byte-for-byte intact. New files ALWAYS go to the --write-dir directory, even
  when the baseline they are versioning past lives somewhere older.
Call the resolved names <final-md>, <docx>, and <packet> below. (draft-v1.md is always left untouched.)

Steps, in order:
1. ${needsRevision
        ? `REVISE mode per your spec (surgeon, not editor): address every must-fix, apply considers only where you agree, touch ONLY cited lines. Write the result to <final-md>. Then run the preservation lint and fix until 0 errors: .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/cover-letter/lint_cover_letter.py "<final-md>" --prev "${draft.draft_path}"`
        : `No revision needed (strong first draft). Copy the draft to <final-md> and run: .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/cover-letter/lint_cover_letter.py "<final-md>" (must be 0 errors).`}
2. Generate the deliverable. DERIVE the filename — never compose it yourself (the candidate half was being improvised, producing two spellings of the same artifact type in one run). Read signature_name from PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/cover-letter/config.json and pass it through the shared canonicalizer, which owns both halves of the name:

     .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/norm_contracts.py --cover-letter-draft-filename \
         --company "${draft.company}" --role "${draft.role}"

   (It takes no candidate name: this .docx is a copy-paste source for the candidate's own template,
   not the artifact they submit — that is the exported PDF, which keeps its candidate prefix.) Use its printed string verbatim as <docx-name>, then run: .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/cover-letter/make_cover_letter_docx.py "<final-md>" -o "${draft.job_folder}/<docx-name>"  — inserting the " - v2" suffix before the extension if versioning per the rule above.
3. Link QA: for each link, curl -sIL -o /dev/null -w "%{http_code}" --max-time 10 "<url>". 200/30x = pass; Medium/LinkedIn 403/999 bot-blocks = verify the URL character-for-character against PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/cover-letter/writing-links.md and mark "matches writing-links". Anything else = flag.
4. Write the COMPACT review packet to <packet> ("coverletter_agent_output - ${draft.company} - ${draft.role}.md" inside the --write-dir directory, plus the " - v2" suffix if versioning) — target ~35 lines, do NOT include the letter text (reconcile reads final.md directly). Exactly these sections:
   # Cover Letter — ${draft.company} — ${draft.role}
   ## Questions for you (resolve before sending)   <- open questions + the writer's declined-fix disagreements + link-QA flags; "None" if empty
   ## Scorecard   <- 3-4 lines: "Fit ${evaluation.fit_score}/5 · Voice ${evaluation.voice_score}/5 (adversarial eval) — N must-fix, all resolved, preservation lint clean"; the one-line GOLD-exemplar comparison; any lint warnings left standing
   ## Links used   <- table: anchor | target | one-line why (or "None" if the letter has no links)
   ## Paste checklist   <- one line: open the .docx, Select All, Copy, paste into your letter template with a formatting-preserving paste (in Pages: regular Paste, NOT "Paste and Match Style"), export PDF, click every link in the PDF

Return (structured): final_md_path, docx_path, review_path, changes_applied, declined, lint_errors, link_qa, remaining_flags.`,
      { agentType: 'cover-letter-writer', phase: 'Finalize', schema: FINALIZE_SCHEMA, label: `finalize:${draft.company}` }
    )
    if (!pkg) throw new Error(`finalize agent failed for ${draft.company}`)
    log(`${draft.company}: done — fit ${evaluation.fit_score}/5, voice ${evaluation.voice_score}/5, links: ${pkg.link_qa}`)
    return {
      job: jobPath,
      company: draft.company,
      role: draft.role,
      folder: draft.job_folder,
      docx: pkg.docx_path,
      review: pkg.review_path,
      scores: { fit: evaluation.fit_score, voice: evaluation.voice_score, must_fix_resolved: evaluation.must_fix.length },
      link_qa: pkg.link_qa,
      open_questions: draft.open_questions,
      remaining_flags: pkg.remaining_flags,
    }
  }
)

const ok = results.filter(Boolean)

// ---- Mark each finished letter in the batch rankings (added 7/16/26) ----
// So the tracker answers "which of these already have a cover letter?" at a glance instead of
// requiring a dig through the job folders. Matches by URL first, then job filename.
if (ok.length) {
  phase('Record')
  const shq = (s) => `'${String(s).replace(/'/g, `'\\''`)}'`
  const cmds = ok.map((L) => {
    const batchDir = `__READY_TO_REVIEW__PRIVATE_GITIGNORED/${batchOf(L.job)}`
    return [
      `PY=".venv/bin/python3"; [ -x "$PY" ] || PY="python3"; "$PY"`,
      `ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/update_rankings_row.py`,
      `--batch ${shq(batchDir)}`,
      `--job-file ${shq(String(L.job).split('/').pop())}`,
      `--cover-letter`,
    ].join(' ')
  })
  await agent(
    `Mark each completed cover letter in its batch rankings.

Run these EXACT shell commands from the project root, in order, and report each one's output verbatim:

${cmds.join('\n')}

Each prints either "Updated ..." (success) or a line starting with "WARNING: no rankings row matched".
Do NOT treat a WARNING as fatal and do NOT retry or "fix" it — just report it. Return a short summary:
how many updated, and the full text of any WARNING lines.`,
    { phase: 'Record', model: 'haiku', label: 'record cover letters in rankings' }
  )
}

// ---- Always end with a paste-ready table (added 7/17/26, mirrors tailor-jobs.js) ----
// Unconditional: the Record-phase writeback only lands where a rankings file exists for the job's
// batch (a backlog letter written outside any current batch has nowhere for that to go), so this
// table is what Jessica actually copies into her Google Sheet regardless.
const table = [
  '| Company | Role | Cover Letter? |',
  '|---|---|---|',
  ...ok.map((L) => `| ${L.company || ''} | ${L.role || ''} | Y |`),
].join('\n')

return {
  letters: ok,
  failed: jobList.length - ok.length,
  table,
  note: `Prepared ${ok.length}/${jobList.length} cover letter(s). Open each "_JAIL Agent Work/coverletter_agent_output - …" packet first (Questions at top), then copy from the .docx into your letter template with a formatting-preserving paste (in Pages: never "Paste and Match Style"). The .docx is the agent's verbatim output — edit only in your own editor; submit as PDF. Each job's "Cover Letter?" column was also marked Y in its batch rankings where one exists. Copy/paste table for your tracker is in the "table" field.`,
}
