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
- NEVER edit any canonical file. Your ONLY write is this folder's reconcile report. Do not touch any repo source files or the learning files (the synthesis stage owns those).
- COVER-LETTER LANE (spec §12; skip if the cover-letter module isn't set up — no 04-TAILOR/cover-letter/feedback-queue.md instance): the agent-side baseline is "_cl_work/final.md" — the candidate NEVER edits the generated .docx, so baseline vs submitted delta IS their feedback. Same observed/inferred firewall. Frame every candidate lesson in plain English: "You did Y on the [Company] letter — on purpose? Make it the default?" with before/after text. Cover-letter lessons are returned separately (cover_letter_findings) — they route to 04-TAILOR/cover-letter/feedback-queue.md, NEVER to the resume learning files. If the letter predates the cover-letter workflow (no baseline), record observed style patterns only, marked "no-baseline".
- EXTRACTION-FIRST (token discipline, spec §13): ALWAYS run .venv/bin/python3 04-TAILOR/learning/extract_submission.py "<folder>" first (cached after the first run). Then read the _extracted/*.txt files and _extracted/coverletter-diff.txt INSTEAD of the PDFs — the diff IS the cover-letter signal (interpret it; don't re-diff). Open a PDF directly only if the manifest shows extraction failed or classified nothing. Read screenshot images ONLY if the manifest lists them AND submitted-answers.txt lacks their content; if you do, append the transcription to _extracted/submitted-answers.txt marked "[transcribed from <filename>]" so no future run ever reads the image again.
- ANECDOTE HARVEST (spec §13; skip if no 04-TAILOR/cover-letter/anecdote-bank.md instance): from the submitted cover letter and answers, extract every personal story / lived detail (family, history, hobbies, personal product use, origin stories) — ESPECIALLY ones the candidate added by hand (in the diff) or that appear nowhere in the anecdote bank. These are the candidate's own words = observed facts; they go DIRECTLY into the bank (tagged with source), not through the queue. Also report bank stories that were REUSED (for Used-in tracking). Never harvest professional claims (those live in the experience bank) — only the personal/lived material.
- ANSWERS LANE (spec §13): from _extracted/submitted-answers.txt, extract each question + the candidate's answer as an archetype pair (why-this-company, how-you-use-AI, etc.) for 04-TAILOR/learning/answer-bank.md. Condense answers >150 words to argument + anecdote slugs. Answers are harvest-only (no baseline exists).`

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
    'base_template_candidate', 'anecdotes', 'answer_pairs', 'cover_letter_findings', 'report_path'],
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
    anecdotes: {
      type: 'array',
      description: 'personal stories/lived details harvested from the submitted letter + answers (spec §13). new=true for stories not in the anecdote bank; new=false to record a reuse for Used-in tracking. Empty if the cover-letter module is not set up.',
      items: {
        type: 'object', additionalProperties: false,
        required: ['slug', 'new', 'story', 'themes', 'use_when'],
        properties: {
          slug: { type: 'string', description: 'kebab-case; match the existing bank slug when new=false' },
          new: { type: 'boolean' },
          story: { type: 'string', description: 'the story in the candidate\'s own (condensed) words; "" when new=false' },
          themes: { type: 'string' },
          use_when: { type: 'string' },
        },
      },
    },
    answer_pairs: {
      type: 'array',
      description: 'application Q&A harvested from submitted-answers.txt (spec §13); empty if no answers found',
      items: {
        type: 'object', additionalProperties: false,
        required: ['archetype', 'question', 'answer_condensed', 'anecdote_slugs'],
        properties: {
          archetype: { type: 'string', description: 'e.g. why-this-company, how-you-use-AI' },
          question: { type: 'string' },
          answer_condensed: { type: 'string', description: 'verbatim if short, else argument + anecdote slugs' },
          anecdote_slugs: { type: 'array', items: { type: 'string' } },
        },
      },
    },
    cover_letter_findings: {
      type: 'object', additionalProperties: false,
      required: ['found', 'baseline_found', 'observed', 'candidates'],
      description: 'Cover-letter lane (spec §12). found = a submitted cover letter was detected (by content, incl. last page of a combined PDF). baseline_found = _cl_work/final.md or generated .docx existed to diff against.',
      properties: {
        found: { type: 'boolean' },
        baseline_found: { type: 'boolean' },
        observed: { type: 'array', items: { type: 'string' }, description: 'factual diffs baseline vs submitted (or "no-baseline" style observations)' },
        candidates: { type: 'array', items: { type: 'string' }, description: 'plain-English candidate lessons: "You did Y on the [Company] letter — on purpose? Make it the default?" with before/after' },
      },
    },
    report_path: { type: 'string' },
  },
}

const SYNTH_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['ledger_entries_added', 'queue_items_touched', 'anecdotes_added', 'anecdote_reuses_tracked', 'answer_entries_added', 'patterns', 'new_finalized_summaries_block', 'notes'],
  properties: {
    ledger_entries_added: { type: 'integer' },
    queue_items_touched: { type: 'integer' },
    anecdotes_added: { type: 'integer' },
    anecdote_reuses_tracked: { type: 'integer' },
    answer_entries_added: { type: 'integer' },
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

STEP 0 — extraction first (token discipline): run
  .venv/bin/python3 04-TAILOR/learning/extract_submission.py "${f.folder_path}"
then read (quote paths — they contain spaces/&/parens):
- The manifest + extracted texts: "_extracted/MANIFEST.txt", "_extracted/submitted-resume.txt", "_extracted/submitted-coverletter.txt", "_extracted/submitted-answers.txt", and "_extracted/coverletter-diff.txt" (if present)
- Scraped JD: "${f.jd_file}"
- Agent recommendation: "${f.output_md}"
- 04-TAILOR/cover-letter/anecdote-bank.md (slugs only — to tell new stories from reuses; skip if it doesn't exist)
Do NOT open the PDFs unless the manifest shows extraction failed (fallback: "${f.final_pdf}"). Screenshots: per the extraction-first rule, read images only if the manifest lists them and their content isn't already in submitted-answers.txt; append transcriptions there once.
${extras}
You MAY read 04-TAILOR/02-resume-index.md to identify which resume base was used vs recommended.

Do:
1. Compare what the agent RECOMMENDED vs what was SUBMITTED (from the extracted texts), per the rules above (observed vs inferred; ignore formatting noise; check confounds).
2. Extract the VERBATIM professional summary from _extracted/submitted-resume.txt (for the summary learning corpus). Also assess base_template_candidate: does this finalized resume cleanly represent a role archetype that future similar roles should COPY rather than rebuild? (one occurrence is enough to flag).
2b. COVER-LETTER LANE (rules above): interpret _extracted/coverletter-diff.txt — every +/- sentence is either formatting noise (say so) or a real edit needing a plain-English candidate lesson. Fill cover_letter_findings either way (found:false is a valid result).
2c. HARVEST (rules above): fill anecdotes (new stories + reuses of bank slugs) and answer_pairs from the extracted letter + answers.
3. WRITE the reconcile report to: ${f.folder_path}/${reportName}
   Use the §2 structure: header (company/role/submitted/reconciled=${RUN_DATE}/status: pending-your-answers/inputs found), then 1.What the agent recommended, 2.What was submitted, 3.Observed changes (fact), 4.Inferred lessons (hypotheses+confidence), 5.Questions for the candidate, 6.Proposed ledger entry, 7.Proposed source-update items (gated), 8.Cover letter (findings, or one line "no cover letter in folder"). This report is your ONLY file write. Do NOT edit any repo source files or the ledger/queue files.
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
1. Read the current ledger and queue. RESPECT existing resolutions — do NOT re-propose things already marked applied / deferred / resolved in them. (One exception: if cover letters were previously marked "deferred" as a lane, that lane is now LIVE via step 4b below — don't re-defer it.)
2. APPEND one ledger entry per NEW folder to the ledger (keyed by folder; status: pending). Do NOT duplicate a folder that already has an entry.
3. Update the ledger's PATTERNS TRACKER: for each recurring lesson, count occurrences across BOTH the new results and existing entries; mark status. A lesson is queue-ready only at >=2 occurrences OR the candidate confirmation (§9).
4. Update the queue: add or increment proposed source-update items. If a proposal recurs, increment its occurrence count and add the application rather than duplicating. New single-occurrence items go to the queue's watch list. CRITICAL (§9a): the watch list is a DURABLE record, not a holding pen — never drop or treat a single-occurrence item as moot. Frame each as "preserved; promotable now on the candidate's confirmation, or auto-surfaced at a 2nd occurrence." Nothing here is auto-applied; everything awaits human review.
4b. COVER-LETTER CANDIDATES (spec §12; skip if the cover-letter module isn't set up): for every result whose cover_letter_findings.candidates is non-empty, APPEND them to 04-TAILOR/cover-letter/feedback-queue.md (folder-keyed, status: pending, idempotent — skip folders already present). Keep each in its plain-English "You did Y on the [Company] letter — on purpose? Make it the default?" form with the before/after text. NEVER write to 04-TAILOR/cover-letter/feedback-ledger.md (promotion is the candidate's manual confirmation) and NEVER route cover-letter lessons into the resume learning files.
4c. ANECDOTE BANK (spec §13; skip if no anecdote-bank instance): merge all anecdotes into 04-TAILOR/cover-letter/anecdote-bank.md following its entry format. new=true -> add a full entry (Status: confirmed, submitted — <Company> <date>) unless a same-story entry already exists (then just update Used in). new=false -> append "<Company> — <Role> (<date>)" to that slug's Used in line if not already listed. These are the candidate's own submitted words — direct entry, no queue.
4d. ANSWER BANK (spec §13): merge all answer_pairs into ${REPO_APP}/learning/answer-bank.md — create it from ${REPO_APP}/learning/answer-bank.template.md if missing; group under existing archetype headings where they match (create the archetype heading if new), each answer tagged "(<Company> — <Role>, <date>)". Idempotent: skip pairs already recorded for that company.
5. BASE AUTO-REGISTRATION (§9b, "submission = seal of approval"): for every result with base_template_candidate.is_candidate=true, EDIT 04-TAILOR/02-resume-index.md directly. Apply the materiality test: new archetype or materially different evidence allocation -> add a named-anchor entry (registry table + a short anchor entry pointing at the finalized resume file in the archive folder, with modules noted); same archetype re-skinned -> add a one-line "newest exemplar" note under the existing anchor. ADDITIVE ONLY: never delete, demote, or rewrite existing entries. List every registration in the returned base_template_candidates field (it is a log of what you registered, not a to-confirm list).
6. Canonical-file discipline (§9b — "submission = seal of approval" covers the candidate's VERBATIM submitted artifacts only): you MAY (a) add base registrations to 04-TAILOR/02-resume-index.md per step 5, and (b) APPEND each folder's verbatim finalized summary (role-archetype labeled, keyed by folder so re-runs don't duplicate) to 05a-summary-library.md, plus any clear, reusable skills observation to 06a-skills-library.md — create either from its template if missing; ALSO return the summaries as new_finalized_summaries_block for visibility. Everything else stays locked: do NOT edit 01-profile.md, 03-approved-truths-and-boundary-rules.md, 04-experience-bank.md, 05-summary-quick.md, 06-skills-quick.md, the cover-letter voice-spec, or the cover-letter feedback-ledger. INFERRED generalizations still go through the queue for the candidate's approval — they approve rules, not their own words. Other permitted writes: ledger + queue (${REPO_APP}/learning/), the cover-letter feedback-queue (4b), the anecdote bank (4c), the answer bank (4d).
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
  anecdotes_added: synth ? synth.anecdotes_added : 0,
  anecdote_reuses_tracked: synth ? synth.anecdote_reuses_tracked : 0,
  answer_entries_added: synth ? synth.answer_entries_added : 0,
  patterns: synth ? synth.patterns : [],
  base_template_candidates: synth ? (synth.base_template_candidates || []) : [],
  finalized_summaries_for_05a: synth ? synth.new_finalized_summaries_block : '',
  archive: discovery.archive_resolved || '',
  workspace_leftovers: leftovers,
  notes: `${synth ? synth.notes : ''}${leftoverNote}`,
}
