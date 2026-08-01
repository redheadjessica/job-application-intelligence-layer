export const meta = {
  name: 'score-profile-fit',
  description: 'Isolated, reliability-gated Profile Fit scorer: one dimension, full §2 procedure, bounded second pass + adjudication. The ONLY production path for Profile Fit.',
  phases: [
    { title: 'Primary', detail: 'one isolated §2 pass per job' },
    { title: 'Verify', detail: 'bounded second blind pass on risk-flagged jobs' },
    { title: 'Adjudicate', detail: 'resolve only material disagreements' },
    { title: 'Persist', detail: 'write results + provenance (migration mode, fail-closed)' },
  ],
}

// args: { jobs: [{key, abs_path}], card, profile, priorByKey?: {key: {score, status}}, anchorsByKey?: {key: anchor} }
// Accept args as an object OR a JSON string (the harness may deliver either).
const A = (typeof args === 'string' && args.trim()) ? JSON.parse(args) : (args || {})
// Jobs may be given as {key, abs_path} objects, or — with srcDir set — as bare filename strings
// (or {key} objects); abs_path is then srcDir/key. Keeps the launch args compact for large batches.
const SRCDIR = (A && typeof A === 'object' && A.srcDir) ? A.srcDir : null
const JOBS = (A.jobs || []).map((j) => {
  if (typeof j === 'string') return { key: j, abs_path: SRCDIR ? `${SRCDIR}/${j}` : j }
  if (j.abs_path) return j
  return { key: j.key, abs_path: SRCDIR ? `${SRCDIR}/${j.key}` : j.key }
})
const CARD = A.card || 'PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/01-scoring-card.md'
const PROFILE = A.profile || 'PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/02-candidate-profile.md'
const PRIOR = A.priorByKey || {}
const ANCHORS = A.anchorsByKey || {}
// Dedicated migration mode: when outDir is set, persist results + provenance to disk (fail-closed),
// so this workflow is self-sufficient for a Profile-Fit-only rescore — no 3-dimension bundle involved.
const OUT = (A && typeof A === 'object' && A.outDir) ? A.outDir : null

// Ledger schema — includes the four SCORER-EMITTED semantic ambiguity flags. Python routing
// reads these booleans; it does not try to infer them from prose.
const LEDGER_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['hiring_thesis', 'centrals', 'narrative_coherence', 'misclassification_check',
    'compounding_applied', 'band_setter', 'band', 'score', 'profile_notes',
    'hiring_thesis_ambiguous', 'centrality_ambiguous', 'independent_gap_ambiguity', 'posting_requirement_conflict'],
  properties: {
    hiring_thesis: { type: 'string' },
    centrals: {
      type: 'array', items: {
        type: 'object', additionalProperties: false,
        required: ['requirement', 'classification', 'grade', 'evidence'],
        properties: {
          requirement: { type: 'string' },
          classification: { type: 'string', enum: ['thesis-defining', 'supporting'] },
          grade: { type: 'string', enum: ['direct', 'transferable', 'light', 'absent'] },
          evidence: { type: 'string' },
        },
      },
    },
    narrative_coherence: { type: 'string' },
    misclassification_check: { type: 'string' },
    compounding_applied: { type: 'boolean' },
    band_setter: { type: 'string' },
    band: { type: 'string' },
    score: { type: 'integer', minimum: 0, maximum: 100 },
    profile_notes: { type: 'string', description: 'one durable sentence naming the band-setter; becomes the Profile Score Notes cell' },
    hiring_thesis_ambiguous: { type: 'boolean' },
    centrality_ambiguous: { type: 'boolean' },
    independent_gap_ambiguity: { type: 'boolean' },
    posting_requirement_conflict: { type: 'boolean' },
  },
}

const ADJ_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['hiring_thesis', 'band_setter', 'band', 'score', 'profile_notes', 'rejected_interpretations'],
  properties: {
    hiring_thesis: { type: 'string' }, band_setter: { type: 'string' }, band: { type: 'string' },
    score: { type: 'integer', minimum: 0, maximum: 100 }, profile_notes: { type: 'string' },
    rejected_interpretations: { type: 'string' },
  },
}

function scorerPrompt(job, passId) {
  return `You are an INDEPENDENT, BLIND Profile-Fit scorer. Score exactly ONE dimension — "How They May See Your Profile" (Profile Fit) — for ONE job, applying the documented procedure faithfully. This is an isolated call: Profile Fit ONLY, no other dimension. Independent pass id: ${passId} (carries no information; ignore it beyond making this run independent).

READ ONLY:
1. The "Profile Fit" / "How They May See Your Profile" section (§2) of "${CARD}" — walk its Step 0→5 procedure: state the HIRING THESIS quoting the posting; enumerate CENTRAL requirements; run the Centrality Test; classify each central THESIS-DEFINING vs SUPPORTING; grade evidence direct/transferable/light/absent with NAMED evidence; run the mandatory MISCLASSIFICATION check; judge narrative coherence; apply the compounding clause (count one gap once); Step 3 "the WEAKEST thesis-defining central sets the band"; the band table 97-100/82-96/68-81/50-67/30-49/0-29; Rules A/B/C; then position within band.
2. Part 1 of "${PROFILE}" — Career Identity, Throughlines, and Common Misclassifications. Reason from these, not bullet-to-bullet resemblance.
3. The job posting — "${job.abs_path}" (WORK DETAILS/COMPENSATION preamble + the text between --- JOB TEXT START --- and --- JOB TEXT END ---).

CLUSTER & AI-MATURITY RULE (enumeration, NOT grade inflation): When a posting expresses ONE specialization through several related bullets, enumerate that specialization as a single coherent requirement CLUSTER — do not collapse the role into its single hardest sub-clause, do not treat multiple phrasings of the same specialization as independent compounding gaps, and do not erase genuine adjacent evidence by grading it \`absent\`. BUT evaluating related requirements as one cluster changes how the requirement is ENUMERATED, not how strongly the candidate evidence is GRADED. Grade the cluster at the HIGHEST maturity level the candidate has ACTUALLY demonstrated; do NOT promote \`light\` to \`transferable\`, or \`transferable\` to \`direct\`, merely because the candidate has several adjacent activities or because the posting states the specialization across several bullets. \`direct\` requires documented OWNERSHIP at substantially the same operating level and environment the role demands: hands-on experimentation, founder/personal-scale building, prototypes, internal tools, or adjacent product work may be meaningful \`light\` or \`transferable\` evidence but are NOT automatically \`direct\` evidence of sustained production deployment, mature evaluation systems, reliability operations, or large-scale consumer/production ownership. When the posting requires multiple facets of a mature AI specialization, set the overall cluster grade from the candidate demonstrated operating MATURITY — do not grade from the strongest adjacent facet while ignoring the missing production-scale facets. For any AI/ML requirement, explicitly locate the candidate's evidence against whatever AI-maturity scale the candidate profile provides, and STATE that level in the ledger's evidence text.

STRICT BLINDNESS — do NOT read any rankings/workbook/tracker/backup or any prior score; do NOT consider Desire, Culture, Practicality, comp, lifestyle, application status, the existing ranking, or the candidate's emotional interest / dream-vs-stepping-stone framing. Score purely from the three sources above.

Return the structured ledger:
- hiring_thesis; centrals[] (requirement + THESIS-DEFINING/SUPPORTING + grade + named evidence); narrative_coherence; misclassification_check; compounding_applied; band_setter (the single thesis-defining central or independent compound that set the band); band; score (0-100 integer); profile_notes (ONE durable sentence that names the band-setter — this becomes the row's permanent explanation).
- FOUR semantic ambiguity flags — set true ONLY when genuinely ambiguous, false otherwise:
  * hiring_thesis_ambiguous: the posting's hiring identity spans two or more loosely-related specializations and which one is THE thesis is genuinely unclear.
  * centrality_ambiguous: for the band-setting requirement, thesis-defining-vs-supporting is a genuine coin-flip.
  * independent_gap_ambiguity: two weak centrals might be one underlying gap or two independent ones (compounding is genuinely unclear).
  * posting_requirement_conflict: the posting is internally unclear whether the band-setting item is central or merely bonus/preferred.
Be rigorous; do not inflate or deflate.`
}

function adjPrompt(job, primary, second) {
  return `You are the ADJUDICATOR for one job's Profile Fit score. Two independent blind scorers materially disagreed. Resolve the exact reasoning disagreement on the evidence — do NOT average, take the median, pick the higher or lower, or anchor to any prior value.

Job file: ${job.abs_path}
You may read: the §2 Profile-Fit procedure in "${CARD}", Part 1 of "${PROFILE}", and the posting above.

PRIMARY ledger: ${JSON.stringify(primary)}
SECOND ledger: ${JSON.stringify(second)}

Decide the contested points (hiring thesis? thesis-defining vs supporting? the pivotal evidence grade? compounding? band-setter?) using the posting language, the profile, and the card's calibration rules. Return: hiring_thesis; band_setter; band; score; profile_notes (one sentence naming the band-setter); rejected_interpretations (why the losing readings were rejected).`
}

// --- JS reliability gate (mirror of ENGINE/03-VETTING/profile_fit_reliability.py) --- //
const GRADE_RANK = { absent: 0, light: 1, transferable: 2, direct: 3 }
const SEMFLAGS = ['hiring_thesis_ambiguous', 'centrality_ambiguous', 'independent_gap_ambiguity', 'posting_requirement_conflict']
const BAND_EDGES = [30, 50, 68, 82, 97]
function thesisDefining(l) { return (l.centrals || []).filter(c => c.classification === 'thesis-defining') }
function weakestTD(l) {
  const td = thesisDefining(l); if (!td.length) return null
  return td.reduce((m, c) => (GRADE_RANK[c.grade] ?? 9) < (GRADE_RANK[m.grade] ?? 9) ? c : m).grade
}
function crossesBoundary(a, b) { if (b == null) return false; const lo = Math.min(a, b), hi = Math.max(a, b); return BAND_EDGES.some(e => lo < e && e <= hi) }
function detFlags(l, prior) {
  const f = []; const td = thesisDefining(l); const below68 = l.score < 68
  if (td.some(c => c.grade === 'absent')) f.push('absent_thesis_central')
  if (td.some(c => c.grade === 'light') && below68) f.push('light_thesis_central_sub68')
  if (l.compounding_applied === true) f.push('compounding')
  if (below68 && (l.centrals || []).filter(c => c.grade === 'direct').length >= 2) f.push('sub68_despite_directs')
  if (prior && prior.score != null && Math.abs(l.score - prior.score) >= 10) f.push('big_move_vs_prior')
  if ((l.centrals || []).some(c => (c.grade === 'direct' || c.grade === 'transferable') && !(c.evidence || '').trim())) f.push('positive_grade_without_evidence')
  if (!(l.band_setter || '').trim()) f.push('missing_band_setter')
  if (prior && prior.status === 'carried') f.push('carried_replaced_by_fresh')
  return f
}
function semFlags(l) { return SEMFLAGS.filter(k => l[k] === true) }
function needsSecond(l, prior) {
  const d = detFlags(l, prior), s = semFlags(l)
  if (d.length || s.length) return { need: true, det: d, sem: s, edge: false }
  const nearEdge = BAND_EDGES.some(e => Math.abs(l.score - e) <= 3)
  const edge = nearEdge && crossesBoundary(l.score, prior && prior.score)
  return { need: edge, det: d, sem: s, edge }
}
function bandOf(s) { return s >= 97 ? '97-100' : s >= 82 ? '82-96' : s >= 68 ? '68-81' : s >= 50 ? '50-67' : s >= 30 ? '30-49' : '0-29' }
const BAND_ORDER = ['0-29', '30-49', '50-67', '68-81', '82-96', '97-100']
function bandsAdjacent(a, b) { const i = BAND_ORDER.indexOf(a), j = BAND_ORDER.indexOf(b); return i >= 0 && j >= 0 && Math.abs(i - j) === 1 }

// Content-sanity: a schema-valid but PLACEHOLDER ledger (the 2026-07-31 validation caught one
// with hiring_thesis="test") must fail closed, not enter the score pool.
const PLACEHOLDER = new Set(['', 'test', 'n/a', 'na', 'tbd', 'todo', 'none', '...'])
function isPlaceholder(l) {
  if (!l) return true
  for (const f of ['hiring_thesis', 'band_setter']) { const v = String(l[f] || '').trim(); if (PLACEHOLDER.has(v.toLowerCase()) || v.length < 12) return true }
  if ((l.centrals || []).some(c => String(c.requirement || '').trim().length < 4)) return true
  return false
}
// Bounded retry: re-invoke a scoring pass on a thrown / empty / placeholder result. Inter-attempt
// backoff is handled by the engine's own per-call retry policy (the workflow sandbox has no timer).
async function scorePass(job, passId, phaseName, tries = 3) {
  let reason = null
  for (let i = 0; i < tries; i++) {
    try {
      const r = await agent(scorerPrompt(job, `${passId}-r${i}`), { schema: LEDGER_SCHEMA, phase: phaseName, label: `${passId}:${job.key}${i ? '#' + i : ''}` })
      if (r && !isPlaceholder(r)) return { ledger: r, retries: i }
      reason = r ? 'placeholder ledger' : 'null/failed result'
    } catch (e) { reason = String((e && e.message) || e) }
  }
  return { ledger: null, retries: tries, error: reason }
}
// Run jobs in small concurrent chunks to keep structured-output failures rare under load.
const CONCURRENCY = 3
async function chunked(items, size, fn) {
  const out = []
  for (let i = 0; i < items.length; i += size) {
    const res = await parallel(items.slice(i, i + size).map(x => () => fn(x)))
    for (const r of res) out.push(r)
  }
  return out
}
const AGREE_SCHEMA = { type: 'object', additionalProperties: false, required: ['substantively_agree', 'reason'], properties: { substantively_agree: { type: 'boolean' }, reason: { type: 'string' } } }
function agreePrompt(a, b) {
  return `Two Profile-Fit ledgers for the SAME job scored within a few points but straddle one band boundary. Decide ONLY whether they SUBSTANTIVELY AGREE — the same hiring thesis, the same thesis-defining centrals, the same pivotal evidence grade, the same compounding decision, the same band-setter, and the same narrative-coherence judgment. Return substantively_agree=true ONLY if ALL of those match (wording may differ); else false with a one-line reason. Do not re-score.\nLEDGER A: ${JSON.stringify(a)}\nLEDGER B: ${JSON.stringify(b)}`
}

phase('Primary')
const results = await chunked(JOBS, CONCURRENCY, async (job) => {
  const prior = PRIOR[job.key] || null
  const p1 = await scorePass(job, 'p1', 'Primary', 3)
  if (!p1.ledger) return { key: job.key, error: `primary scoring failed: ${p1.error}`, final_score: null,
    validation: { second_pass: false, adjudicated: false, primary_retries: p1.retries, failure_reason: p1.error } }
  const primary = p1.ledger
  const gate = needsSecond(primary, prior)
  let out = {
    key: job.key, final_score: primary.score, band: bandOf(primary.score),
    status: 'fresh', ledger: primary, profile_notes: primary.profile_notes,
    risk_flags: [...gate.det, ...gate.sem, ...(gate.edge ? ['band_edge_cross'] : [])],
    validation: { second_pass: false, adjudicated: false, primary_retries: p1.retries }, passes: [primary],
  }
  if (!gate.need) return out                              // single pass accepted

  const p2 = await scorePass(job, 'p2', 'Verify', 3)
  out.validation.second_pass = true
  out.validation.second_retries = p2.retries
  if (!p2.ledger) { out.validation.failure_reason = `second pass failed: ${p2.error}`; return out }  // fail closed
  const second = p2.ledger; out.passes.push(second)

  const spread = Math.abs(primary.score - second.score)
  const sameBand = bandOf(primary.score) === bandOf(second.score)
  const adjBand = bandsAdjacent(bandOf(primary.score), bandOf(second.score))
  const samePivotal = weakestTD(primary) === weakestTD(second)
  const compDiff = !!primary.compounding_applied !== !!second.compounding_applied
  const materialNum = spread > 10 || (!sameBand && !adjBand) || compDiff

  if (!materialNum && spread <= 5 && samePivotal && sameBand) return out   // retain primary (same band)
  if (!materialNum && spread <= 5 && samePivotal && adjBand) {
    // Adjacent-band exception: retain primary ONLY if a verifier confirms full substantive agreement.
    const agree = await agent(agreePrompt(primary, second), { schema: AGREE_SCHEMA, phase: 'Verify', label: `pfagree:${job.key}` })
    if (agree && agree.substantively_agree) { out.validation.adjacent_band_accepted = true; return out }
  }
  // otherwise adjudicate on the evidence
  const adj = await agent(adjPrompt(job, primary, second), { schema: ADJ_SCHEMA, phase: 'Adjudicate', label: `pfadj:${job.key}` })
  if (adj) {
    out.validation.adjudicated = true; out.status = 'adjudicated'
    out.final_score = adj.score; out.band = bandOf(adj.score); out.profile_notes = adj.profile_notes
    out.adjudication = adj
  } else { out.validation.failure_reason = 'adjudication failed' }   // fail closed
  return out
})

const finalResults = results.filter(Boolean)

// ---- Dedicated migration-mode persistence: write results + provenance (fail-closed) ---- //
if (OUT) {
  phase('Persist')
  const byKey = {}
  for (const j of JOBS) byKey[j.key] = j.abs_path
  const resultsPath = `${OUT}/profile-fit-results.json`
  const provPath = `${OUT}/profile-fit-provenance.json`
  const payload = JSON.stringify({ results: finalResults.map((r) => ({
    key: r.key, abs_path: byKey[r.key] || null,
    final_score: r.final_score, band: r.band, status: r.status || 'fresh',
    profile_notes: r.profile_notes,
    ledger: r.ledger || null, risk_flags: r.risk_flags || [], validation: r.validation || {},
    adjudication: r.adjudication || null,
  })) }, null, 1)
  const WRITE_SCHEMA = { type: 'object', additionalProperties: false, required: ['wrote'],
    properties: { wrote: { type: 'array', items: { type: 'string' } } } }
  await agent(
    `Write this file EXACTLY as given, overwriting if it exists. Do not modify the content.\n\n=== FILE: ${resultsPath} ===\n${payload}`,
    { phase: 'Persist', label: 'write pf-results', schema: WRITE_SCHEMA })
  const PROV_SCHEMA = { type: 'object', additionalProperties: false, required: ['provenance_written'],
    properties: { provenance_written: { type: 'boolean' }, note: { type: 'string' } } }
  const provRes = await agent(
    `Run this bash command and report whether provenance was written. Set provenance_written=true ONLY if the command exits 0 and prints a line starting with "provenance OK"; else false with the error in note.\n` +
    `\`\`\`bash\nPY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"; "$PY" ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/persist_profile_fit.py --results "${resultsPath}" --provenance "${provPath}" --card "${CARD}" --profile "${PROFILE}" --prompt ".claude/workflows/score-profile-fit.js" --date "$(date +%F)"\n\`\`\``,
    { phase: 'Persist', label: 'persist provenance', schema: PROV_SCHEMA })
  return { results: finalResults, persisted: !!(provRes && provRes.provenance_written),
    resultsPath, provPath, provNote: provRes && provRes.note }
}

return { results: finalResults }
