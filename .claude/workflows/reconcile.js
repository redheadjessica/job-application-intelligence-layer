export const meta = {
  name: 'reconcile',
  description: 'Post-application learning: reconcile completed submitted applications (compare the agent\'s recommendation vs the finalized submitted resume), write a per-folder reconcile report, and merge candidate lessons into the learning ledger + source-update queue (04-TAILOR/learning/). Never edits canonical generation files. Implements 04-TAILOR/learning/reconcile-spec.md.',
  whenToUse: 'After applications are submitted and moved to your submitted-applications archive (use /archive to move them). {archive} is OPTIONAL — without it, reconcile reads archive.path from jail.config.json (fallback 05-SUBMITTED-APPLICATIONS) and scans its year subfolders. Pass {folders:[...]} for an explicit set, or {limit:N} to cap. Cadence: run it after your first few applications, after a meaningfully changed final resume, when a new resume base emerges, or after repeated summary/skills corrections — less often once things stabilize. Vet/tailor is unrelated.',
  phases: [
    { title: 'Discover', detail: 'find ready, unreconciled submitted-application folders', model: 'haiku' },
    { title: 'Reconcile', detail: 'one agent per folder: diff recommendation vs final PDF, write the report', model: 'sonnet' },
    { title: 'Synthesize', detail: 'merge candidates into the learning ledger + queue (single writer)', model: 'sonnet' },
  ],
}

// ---- Inputs ----
let A = args
if (typeof A === 'string') { try { A = JSON.parse(A) } catch (_) { /* leave raw */ } }
A = (A && typeof A === 'object') ? A : {}
const ARCHIVE = A.archive || ''   // empty -> discover resolves it from jail.config.json archive.path (fallback 05-SUBMITTED-APPLICATIONS)
const FOLDERS = Array.isArray(A.folders) ? A.folders : null   // explicit list (names or abs paths)
const LIMIT = Number.isInteger(A.limit) ? A.limit : null      // cap when scanning
const REPO_APP = '04-TAILOR'                                   // learning files live in 04-TAILOR/learning/ (repo-relative)

// Condensed reconcile rules, inlined so per-folder agents don't each re-read the 200-line spec.
const RULES = `RECONCILE RULES (condensed from 04-TAILOR/learning/reconcile-spec.md):
- OBSERVED = fact from comparing the agent's recommendation (.md) vs the FINAL submitted PDF (ground truth): a bullet present in one not the other, a changed word, a different base, a softened/corrected claim, a style edit. State plainly. IGNORE pure formatting / .pages->PDF noise (whitespace, line breaks, glyph/ligature extraction) — semantic content only.
- INFERRED = a hypothesis about WHY, or a generalizable lesson. ALWAYS label category (routing | missed-evidence | claim-boundary | voice | skills | content) + confidence (high|med|low). NEVER state intent as fact. Observed and inferred never mix.
- Classification: everything starts as an observation. It becomes a QUESTION when the "why" is ambiguous and the answer changes whether it's a lesson. It becomes a CANDIDATE LEDGER entry when there's a plausible lesson (low bar). It becomes a PROPOSED SOURCE-UPDATE only at the HIGH bar: a specific, named-file edit AND (confirmed by the candidate OR recurs >=2 apps). One-offs are observations/questions, NOT proposed updates.
- Confounds: check timing. Several "overrides" may already be incorporated into the current system (e.g. base overrides that became canonical bases; pre-rule submissions). Flag these as confounds, not new lessons.
- SINGLE OCCURRENCE IS NOT MOOT (§9a): the >=2 gate governs only auto-promotion of unconfirmed RULE edits. A one-off can be the most valuable thing in a batch. Record every single-occurrence insight; it is promotable now on the candidate's confirmation. Never discard something as moot just because it appears once.
- BASE / TEMPLATE CANDIDATE (§9a, copy-don't-rebuild): a finalized resume is itself a reusable artifact. If this submitted resume cleanly represents a role archetype (e.g. "healthcare + mobile + retention"), FLAG it as a base/template candidate — name the archetype and recommend future similar roles copy THIS exact resume rather than rebuild. One occurrence is enough to flag; promotion to the resume index is confirmation-only and is NOT subject to the >=2 gate.
- NEVER edit any canonical file. Your ONLY write is this folder's reconcile report. Do not touch the job-pipeline repo or the learning files (the synthesis stage owns those).`

// ---- Schemas ----
const DISCOVER_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['run_date', 'ready', 'skipped'],
  properties: {
    run_date: { type: 'string', description: 'today as MM-DD-YY (from `date +%m-%d-%y`)' },
    ready: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['folder_path', 'company', 'role', 'submitted_date', 'jd_file', 'output_md', 'final_pdf'],
        properties: {
          folder_path: { type: 'string', description: 'absolute path to the submitted-application folder' },
          company: { type: 'string' },
          role: { type: 'string' },
          submitted_date: { type: 'string', description: 'from the folder name if present, else "unknown"' },
          jd_file: { type: 'string', description: 'filename of the scraped job post' },
          output_md: { type: 'string', description: 'filename of application_resume_output*.md' },
          final_pdf: { type: 'string', description: 'filename of the final submitted resume PDF' },
          cover_letter: { type: 'string', description: 'filename if present, else ""' },
          answers: { type: 'string', description: 'application-answers filename if present, else ""' },
        },
      },
    },
    skipped: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['folder', 'reason'],
        properties: { folder: { type: 'string' }, reason: { type: 'string' } },
      },
    },
    archive_resolved: { type: 'string', description: 'the archive path actually scanned (from {archive}, else jail.config.json archive.path, else the 05-SUBMITTED-APPLICATIONS fallback)' },
    workspace_leftovers: { type: 'array', items: { type: 'string' }, description: 'completed-looking folders still under __READY TO REVIEW (they contain a final resume PDF) — a cleanliness warning only; NEVER moved by reconcile' },
  },
}

const RECONCILE_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['folder_path', 'company', 'role', 'base_recommended', 'base_used', 'agreed_or_overrode',
    'observed', 'inferred', 'questions', 'candidate_ledger', 'proposed_updates', 'finalized_summary',
    'base_template_candidate', 'report_path'],
  properties: {
    folder_path: { type: 'string' },
    company: { type: 'string' },
    role: { type: 'string' },
    submitted_date: { type: 'string' },
    base_recommended: { type: 'string' },
    base_used: { type: 'string' },
    agreed_or_overrode: { type: 'string', enum: ['agreed', 'overrode', 'mixed', 'unknown'] },
    observed: { type: 'array', items: { type: 'string' }, description: 'terse factual diffs' },
    inferred: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['category', 'confidence', 'lesson'],
        properties: {
          category: { type: 'string', enum: ['routing', 'missed-evidence', 'claim-boundary', 'voice', 'skills', 'content'] },
          confidence: { type: 'string', enum: ['high', 'med', 'low'] },
          lesson: { type: 'string' },
        },
      },
    },
    questions: { type: 'array', items: { type: 'string' } },
    candidate_ledger: { type: 'string', description: 'terse ledger entry for this application' },
    proposed_updates: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['target_file', 'change', 'confidence', 'gate'],
        properties: {
          target_file: { type: 'string' },
          change: { type: 'string' },
          confidence: { type: 'string', enum: ['high', 'med', 'low'] },
          gate: { type: 'string', enum: ['needs-confirmation', 'needs-2nd-occurrence'] },
        },
      },
    },
    finalized_summary: { type: 'string', description: 'the verbatim professional summary from the FINAL submitted PDF' },
    base_template_candidate: {
      type: 'object', additionalProperties: false,
      required: ['is_candidate', 'archetype', 'recommendation'],
      description: 'Is this finalized resume a clean, reusable base/template for a role archetype (copy-don\'t-rebuild)? Single occurrence is enough to FLAG; promotion is confirmation-only by the candidate.',
      properties: {
        is_candidate: { type: 'boolean' },
        archetype: { type: 'string', description: 'e.g. "healthcare + mobile + retention"; "" if not a candidate' },
        recommendation: { type: 'string', description: 'why future similar roles should copy this exact resume; "" if not a candidate' },
      },
    },
    report_path: { type: 'string' },
  },
}

const SYNTH_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['ledger_entries_added', 'queue_items_touched', 'patterns', 'new_finalized_summaries_block', 'notes'],
  properties: {
    ledger_entries_added: { type: 'integer' },
    queue_items_touched: { type: 'integer' },
    patterns: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['lesson', 'category', 'occurrences', 'status'],
        properties: {
          lesson: { type: 'string' }, category: { type: 'string' },
          occurrences: { type: 'integer' }, status: { type: 'string' },
        },
      },
    },
    new_finalized_summaries_block: { type: 'string', description: 'ready-to-paste markdown for 05a (NOT written by this workflow)' },
    base_template_candidates: {
      type: 'array',
      description: 'finalized resumes flagged as reusable base/template candidates (copy-don\'t-rebuild), for the candidate to confirm into 02-resume-index',
      items: {
        type: 'object', additionalProperties: false,
        required: ['company', 'archetype', 'recommendation'],
        properties: { company: { type: 'string' }, archetype: { type: 'string' }, recommendation: { type: 'string' } },
      },
    },
    notes: { type: 'string' },
  },
}

// ---- Phase 1: Discover ----
phase('Discover')
const scopeLine = FOLDERS
  ? `Process ONLY these folders (names are relative to the archive unless already absolute):\n${FOLDERS.map((f) => '- ' + f).join('\n')}`
  : (ARCHIVE
      ? `Scan the archive "${ARCHIVE}" (including its year subfolders, e.g. <archive>/2026/) for application folders.${LIMIT ? ` Limit to the ${LIMIT} most recent ready folders.` : ''}`
      : `No archive path was passed. Resolve it: read jail.config.json -> archive.path; if the file is missing or invalid, fall back to "05-SUBMITTED-APPLICATIONS" (note which you used in archive_resolved). Then scan that archive INCLUDING its year subfolders (e.g. <archive>/2026/) for application folders.${LIMIT ? ` Limit to the ${LIMIT} most recent ready folders.` : ''}`)

const discovery = await agent(
  `You are the discovery step of the reconcile workflow (04-TAILOR/learning/reconcile-spec.md §5 readiness).

${scopeLine}

Steps:
1. Run \`date +%m-%d-%y\` and return it as run_date.
2. List the archive's application folders, INCLUDING any year subfolders ("<archive>/<YYYY>/<app folder>"). An APPLICATION folder contains an "application_resume_output*.md". (An "archive-summary.md" may also be present — it does NOT block reconcile.)
3. READINESS (§5) — a folder is READY only if ALL hold; otherwise add it to "skipped" with a reason:
   - it has an original "application_resume_output*.md",
   - it has a FINAL submitted resume PDF (a "*Resume*.pdf", or the single non-JD .pdf in the folder; a .pages alone is NOT enough),
   - it has a scraped job post (a .txt, or a "Job Application*"/"* Job*" PDF),
   - it does NOT already contain a "reconcile-report - *.md" (else already done -> skip with reason "already reconciled"),
   - it is under your submitted-applications archive (not __READY TO REVIEW).
4. For each READY folder, identify the exact filenames: jd_file, output_md, final_pdf, and (if present) cover_letter and answers. Derive company, role, and submitted_date from the folder name (e.g. "Acme - Sr Analyst - 01-15-26" -> company "Acme", role "Sr Analyst", date "01-15-26").
5. Return "archive_resolved" = the archive path you actually scanned (the passed archive, the jail.config.json archive.path, or the "05-SUBMITTED-APPLICATIONS" fallback).
6. WORKSPACE LEFTOVERS (cleanliness warning — do NOT move anything): also look under "__READY TO REVIEW/*/2 - Tailored Resumes/*" for completed-looking folders (ones containing a final resume PDF — a "*Resume*.pdf" or a single non-JD .pdf). Return their folder names in "workspace_leftovers". They are NOT reconciled here; they're surfaced so the user can archive them with /archive.
Use ls and quote paths (folders contain spaces, &, parentheses). Return absolute folder_path values.`,
  { phase: 'Discover', model: 'haiku', schema: DISCOVER_SCHEMA, label: 'discover folders' }
)

const leftovers = (discovery && discovery.workspace_leftovers) || []
const leftoverNote = leftovers.length
  ? ` Also: ${leftovers.length} completed-looking folder(s) still in __READY TO REVIEW — if those were submitted, archive them with /archive (${leftovers.join(', ')}).`
  : ''
if (!discovery || !Array.isArray(discovery.ready) || discovery.ready.length === 0) {
  return { reconciled: 0, ready: 0, skipped: discovery ? discovery.skipped : [], archive: discovery ? discovery.archive_resolved : '', workspace_leftovers: leftovers, note: `No ready, unreconciled folders found.${leftoverNote}` }
}
const RUN_DATE = discovery.run_date
log(`Reconciling ${discovery.ready.length} folder(s); ${(discovery.skipped || []).length} skipped. Run date ${RUN_DATE}.`)

// ---- Phase 2: Reconcile (parallel, one agent per folder) ----
phase('Reconcile')
const results = (await parallel(discovery.ready.map((f) => async () => {
  const reportName = `reconcile-report - ${f.company} - ${f.role} - ${RUN_DATE}.md`
  const extras = [
    f.cover_letter ? `Cover letter: "${f.cover_letter}"` : null,
    f.answers ? `Application answers: "${f.answers}"` : null,
  ].filter(Boolean).join('\n')
  const r = await agent(
    `Reconcile ONE completed application. ${RULES}

Folder (absolute): ${f.folder_path}
Read these (all inside that folder; quote paths — they contain spaces/&/parens):
- Scraped JD: "${f.jd_file}"
- Agent recommendation: "${f.output_md}"
- FINAL submitted resume PDF (ground truth): "${f.final_pdf}"
${extras}
You MAY read 04-TAILOR/02-resume-index.md to identify which resume base was used vs recommended.

Do:
1. Compare what the agent RECOMMENDED vs what was SUBMITTED, per the rules above (observed vs inferred; ignore formatting noise; check confounds).
2. Extract the VERBATIM professional summary from the FINAL PDF (for the summary learning corpus). Also assess base_template_candidate: does this finalized resume cleanly represent a role archetype that future similar roles should COPY rather than rebuild? (one occurrence is enough to flag).
3. WRITE the reconcile report to: ${f.folder_path}/${reportName}
   Use the §2 structure: header (company/role/submitted/reconciled=${RUN_DATE}/status: pending-your-answers/inputs found), then 1.What the agent recommended, 2.What was submitted, 3.Observed changes (fact), 4.Inferred lessons (hypotheses+confidence), 5.Questions for the candidate, 6.Proposed ledger entry, 7.Proposed source-update items (gated). This report is your ONLY file write. Do NOT edit anything in the job-pipeline repo or the ledger/queue files.
4. Return the structured result (report_path = the file you wrote).`,
    { phase: 'Reconcile', model: 'sonnet', schema: RECONCILE_SCHEMA, label: `${f.company}` }
  )
  return r
}))).filter(Boolean)

if (results.length === 0) {
  return { reconciled: 0, ready: discovery.ready.length, skipped: discovery.skipped, note: 'All reconcile agents returned empty.' }
}
log(`${results.length} reconcile reports written. Synthesizing into the ledger + queue.`)

// ---- Phase 3: Synthesize (single writer for the global ledger/queue) ----
phase('Synthesize')
const RESULTS_JSON = JSON.stringify(results, null, 1)
const synth = await agent(
  `You are the SINGLE writer that merges reconcile results into the global learning files. ${RULES}

Inputs: the per-folder reconcile results (JSON) below, plus the CURRENT state of these LEARNING instances (all gitignored, append-only — read whichever already exist):
- ${REPO_APP}/learning/learning-ledger.md      (the ledger)
- ${REPO_APP}/learning/source-update-queue.md  (the queue)
- ${REPO_APP}/05a-summary-library.md           (the finalized-summary corpus)
- ${REPO_APP}/06a-skills-library.md            (the skills calibration log)
If one of these four instances does NOT exist but its "*.template.md" sibling does, create the instance from the template's structure first, then append. NEVER create or write the primary generation files (01-06, resume index, experience bank, 05-summary-quick, 06-skills-quick).

RESULTS JSON:
${RESULTS_JSON}

Do, carefully:
1. Read the current ledger and queue. RESPECT existing resolutions — do NOT re-propose things already marked applied / deferred / resolved (e.g. cover letters = deferred; "AI-powered" = applied; "First PM hire" = resolved confound; protect-concrete-proof = applied; summary-as-strategy-input = resolved).
2. APPEND one ledger entry per NEW folder to the ledger (keyed by folder; status: pending). Do NOT duplicate a folder that already has an entry.
3. Update the ledger's PATTERNS TRACKER: for each recurring lesson, count occurrences across BOTH the new results and existing entries; mark status. A lesson is queue-ready only at >=2 occurrences OR the candidate confirmation (§9).
4. Update the queue: add or increment proposed source-update items. If a proposal recurs, increment its occurrence count and add the application rather than duplicating. New single-occurrence items go to the queue's watch list. CRITICAL (§9a): the watch list is a DURABLE record, not a holding pen — never drop or treat a single-occurrence item as moot. Frame each as "preserved; promotable now on the candidate's confirmation, or auto-surfaced at a 2nd occurrence." Nothing here is auto-applied; everything awaits human review.
5. BASE / TEMPLATE CANDIDATES (§9a): collect every result with base_template_candidate.is_candidate=true into the returned base_template_candidates list, and record them in the queue's "Base / template candidates" subsection (copy-don't-rebuild; archetype + recommendation). These are confirmation-only registry additions and are NOT subject to the >=2 gate — surface them clearly for the candidate even at one occurrence.
6. APPEND to the learning libraries (append-only PRIVATE instances, NOT primary source files): add each finalized, submitted summary (verbatim, role-archetype labeled, keyed by folder so re-runs don't duplicate) to 05a-summary-library.md; add any clear, reusable skills observation from this batch to 06a-skills-library.md. Create either instance from its template if missing. ALSO return the same summaries as new_finalized_summaries_block (paste-ready, for convenience). Do NOT touch the PRIMARY source-of-truth files — 01-profile.md, 02-resume-index.md, 03-approved-truths-and-boundary-rules.md, 04-experience-bank.md, 05-summary-quick.md, 06-skills-quick.md: any change to those is only a PROPOSAL in the source-update queue, gated on human review (§9).
7. Keep the ledger and queue tight and honest; flag confounds explicitly.

Write the updated ledger and queue, then return the structured summary.`,
  { phase: 'Synthesize', model: 'sonnet', schema: SYNTH_SCHEMA, label: 'merge ledger/queue' }
)

return {
  reconciled: results.length,
  ready: discovery.ready.length,
  skipped: discovery.skipped || [],
  run_date: RUN_DATE,
  reports: results.map((r) => r.report_path),
  ledger_entries_added: synth ? synth.ledger_entries_added : 0,
  queue_items_touched: synth ? synth.queue_items_touched : 0,
  patterns: synth ? synth.patterns : [],
  base_template_candidates: synth ? (synth.base_template_candidates || []) : [],
  finalized_summaries_for_05a: synth ? synth.new_finalized_summaries_block : '',
  archive: discovery.archive_resolved || '',
  workspace_leftovers: leftovers,
  notes: `${synth ? synth.notes : ''}${leftoverNote}`,
}
