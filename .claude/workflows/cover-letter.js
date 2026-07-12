export const meta = {
  name: 'cover-letter',
  description: 'Draft -> lint -> dual eval (fit + voice) -> finalize (surgical revise + .docx + link QA + compact scorecard), for one or more jobs.',
  whenToUse: 'Pass {jobs: ["path/to/job.txt", ...]} (or {job: "path"}). Optional {out: "explicit output folder"} when a job folder already exists. Requires the cover-letter instances (run /cover-letter-intake first).',
  phases: [
    { title: 'Draft', detail: 'writer agent, lint-gated' },
    { title: 'Evaluate', detail: 'fit + voice scores, adversarial, self-pushback' },
    { title: 'Finalize', detail: 'surgical fixes + anti-smoothing lint + .docx + link QA + packet' },
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

// Derive the batch the same way tailor-jobs does, so letters land beside resume drafts.
function batchOf(p) {
  const parts = String(p || '').replace(/\/+$/, '').split('/')
  const idx = parts.indexOf('__READY TO REVIEW')
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

  // ---- Stage 1: Draft ----
  async (jobPath) => {
    const destParent = outOverride || `__READY TO REVIEW/${batchOf(jobPath)}/2 - Tailored Resumes`
    const draft = await agent(
      `DRAFT mode. Write ONE cover letter per your spec (.claude/agents/cover-letter-writer.md rules apply — read the candidate's canon files first; feedback-ledger newest entries win).

Job description file (read this exact file): ${jobPath}

Working location: ${outOverride
        ? `use this existing folder directly: "${outOverride}"`
        : `find or create the job folder inside "${destParent}" using the "Company - Role" naming convention (no date; abbreviate Product Manager -> PM, Vice President -> VP; mkdir -p with quoted paths). If a folder for this company/role already exists there, use it.`}

Inside the job folder create a work directory "_cl_work/" and write your draft to "_cl_work/draft-v1.md". Run the lint gate on it as your spec requires. ${NO_WRAP}

Return (structured): job_folder, draft_path, company, role, links_used [{anchor,url,why}], word_count, lint_errors (must be 0), lint_warnings [strings], open_questions [strings].`,
      { agentType: 'cover-letter-writer', phase: 'Draft', schema: DRAFT_SCHEMA, label: `draft:${jobPath.split('/').pop()}` }
    )
    if (!draft) throw new Error(`draft agent failed for ${jobPath}`)
    if (draft.lint_errors > 0) log(`WARNING: draft for ${draft.company} returned with ${draft.lint_errors} lint errors`)
    return { jobPath, draft }
  },

  // ---- Stage 2: Evaluate ----
  async ({ jobPath, draft }) => {
    const evaluation = await agent(
      `Evaluate ONE cover letter draft per 04-TAILOR/cover-letter/eval-rubric.md (read it first, follow it exactly — including any dose rules in the feedback ledger).

Draft: ${draft.draft_path}
Job description: ${jobPath}
Job folder (check for application_resume_output): ${draft.job_folder}

Write your evaluation to "${draft.job_folder}/_cl_work/eval-1.md". Keep it TERSE — max ~40 lines, findings only, no restating the letter. ${NO_WRAP}

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

Steps, in order:
1. ${needsRevision
        ? `REVISE mode per your spec (surgeon, not editor): address every must-fix, apply considers only where you agree, touch ONLY cited lines. Write the result to "_cl_work/final.md" (leave draft-v1.md untouched). Then run the preservation lint and fix until 0 errors: .venv/bin/python3 04-TAILOR/cover-letter/lint_cover_letter.py "<final.md>" --prev "${draft.draft_path}"`
        : `No revision needed (strong first draft). Copy the draft to "_cl_work/final.md" and run: .venv/bin/python3 04-TAILOR/cover-letter/lint_cover_letter.py "<final.md>" (must be 0 errors).`}
2. Generate the deliverable: read signature_name from 04-TAILOR/cover-letter/config.json, hyphenate it (e.g. "Jordan Lee" -> "Jordan-Lee"), then run: .venv/bin/python3 04-TAILOR/cover-letter/make_cover_letter_docx.py "<final.md>" -o "${draft.job_folder}/<Hyphenated-Name>-CoverLetter - ${draft.company} - ${draft.role}.docx"
3. Link QA: for each link, curl -sIL -o /dev/null -w "%{http_code}" --max-time 10 "<url>". 200/30x = pass; Medium/LinkedIn 403/999 bot-blocks = verify the URL character-for-character against 04-TAILOR/cover-letter/writing-links.md and mark "matches writing-links". Anything else = flag.
4. Write the COMPACT review packet to "${draft.job_folder}/application_coverletter_output - ${draft.company} - ${draft.role}.md" — target ~35 lines, do NOT include the letter text (reconcile reads _cl_work/final.md directly). Exactly these sections:
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
return {
  letters: ok,
  failed: jobList.length - ok.length,
  note: `Prepared ${ok.length}/${jobList.length} cover letter(s). Open each "application_coverletter_output - …" packet first (Questions at top), then copy from the .docx into your letter template with a formatting-preserving paste (in Pages: never "Paste and Match Style"). The .docx is the agent's verbatim output — edit only in your own editor; submit as PDF.`,
}
