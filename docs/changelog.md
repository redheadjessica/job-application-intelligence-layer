# JAIL Changelog

Project changelog. Reverse chronological. Maintained as readable project memory: what
changed, what was explored, and why it mattered — not a commit log. Git history already
holds the granular record; this file is the curated account.

Add rough entries here during normal work (see `scripts/README.md` for the format).
Run `python3 scripts/doc_synthesis.py` to consolidate them into readable threads.


<!-- changelog-processed-through: bd576955caf6495566fc88fcf9b7b5aadb8d10c8 -->
---

## 2026-07-29 (later still) — Two more identity defects, caught by actually re-fetching

Re-fetching the renamed captures (rather than trusting the dry run) exposed two more cases the same
live page can produce on a different visit:

- **A page title that names the PAGE, not the job** — a careers site served `job details` as its title
  with the real role sitting in the *company* slot. Generic page titles (`job details`, `job
  description`, `open positions`, `apply now`, …) are now treated as branding, i.e. as carrying no role
  information, so recovery runs instead of the page label becoming the role.
- **The employer's own name could mask the real title line.** Employer-name words were treated as
  navigation vocabulary outright, so when the company slot held the ROLE text, the body's matching title
  line looked like pure chrome and was skipped (the scan then reached for a benefits bullet). Employer
  names now only count as nav vocabulary *in combination with* a real nav word — which is all that case
  ("Working at <Employer>") ever needed.

Two further rounds on the same URL (it served a different chrome title on literally every fetch):

- **Title recovery read `<h2>` as a title signal. It isn't.** On that page the h1 was "job details" and
  the h2 list ran "Jobs search results" / "Follow Life at &lt;Employer&gt; on" / "More about us" — footer
  chrome that outranked the body's own first content line and became the captured role. Recovery now
  reads **h1 only**, per the spec's chain (JSON-LD title → first h1 → first non-navigation body heading).
  The primary fetch path's separate branded-h1-then-real-h2 handling is unaffected.
- **Branding detection generalized past a fixed list**: a short label built ENTIRELY of page-navigation
  vocabulary is chrome, whatever the wording. A fixed list of generic page titles was losing a
  whack-a-mole against one SPA.

Lesson worth keeping: for capture identity, a dry run over saved files is necessary but not sufficient —
the same URL can serve different chrome on a different visit, so re-fetch before declaring it fixed. Four
fetches of one URL produced four different titles; only the last two were usable.

Recommended follow-up (NOT implemented — outside the spec's recovery chain): several careers URLs carry
the role slug in the path (`…/results/<id>-product-manager-workspace-ecosystem`). That is a
high-confidence, offline title source and would have resolved this page on the first attempt.


## 2026-07-29 (later) — Three captured-identity defects caught by dry-running the new normalizer over a real batch

Before retro-applying the fixed identity normalizer to a real batch, I dry-ran it over all 51
captures and diffed the filenames it would produce. That surfaced three defects — two of them
long-standing, one introduced by the fix itself — which is a strong argument for always dry-running a
rename pass over real data before acting on it:

- **A company named INSIDE a longer title was being treated as role-as-company.** The
  never-role-as-company guard fired on mere substring containment, so a title that legitimately names
  its own employer ("Director, Product Management, <Employer> Consumer") caused the correct,
  ATS-authoritative employer name to be swapped for a domain-derived *parent-company* name the user
  would not recognize. Containment now only counts when the company accounts for most of the title.
- **The new title recovery could overwrite a probably-correct title with page chrome.** When a
  non-branding title merely COLLIDES with the company, that ambiguity can equally mean the *company* is
  wrong — and one real capture would have taken "linkCopy link" out of the body as its role. Body-text
  recovery is now reserved for titles that carry no role information at all (missing or pure branding);
  a collision may only be corrected from a high-confidence structured source (JSON-LD / a heading), and
  an unresolved collision keeps its role text rather than being failed loudly. Extraction glue with
  run-together case ("linkCopy link", "emailEmail a friend") is rejected outright as a title candidate.
- **A big employer's own careers site could yield no company name at all.** Hosts that double as job
  boards were unconditionally refused as employer names, so a careers-site posting whose title also sat
  in the company slot had no alternative available and the filename doubled the role
  (`<role>__<role>.txt`). On an explicit `/careers` path the host does name the employer, so it is now
  accepted there (a plain board path still isn't).


## 2026-07-29 (authoritative) — The output-contract spec supersedes every earlier location-color rule; three fidelity gaps fixed

**Read this before trusting any older colour or format note in this file.** The 2026-07-29
output-contract specification is now the authoritative source for Working Location text + colours,
Comp Range, Comp Fit, Lane, tailored-application names, and captured-job filenames. It **supersedes**:

- the **2026-07-14 (later still)** location-colour rule (home-metro **1–2** days → yellow, **3+** →
  orange). Under the current contract an acceptable home-metro office at **exactly 1, 2, or 3 days is
  YELLOW**; only *more than* 3 days, an open-ended minimum (`3+`, "at least 3"), or an unknown cadence
  is orange. That entry also claimed the shared engine already coloured location correctly — it did not.
- the earlier **2026-07-29** "day-count coloring ported" entry, which described the interim palette and
  said `Unknown` renders **grey**. Grey is no longer permitted anywhere in these two columns: the only
  values are green `42FF35`, yellow `FDFF43`, orange `FA9C31`, red `F82C1F`, with black text, and
  `Unknown` is **orange**. The old palette (`A9D08E` / `FFE699` / `F4B183` / `D9D9D9` / `F4A6A6`) is
  retired for Working Location and Location Fit, and a regression test asserts none of it can reappear.
- any note implying `location.arrangements` drives a colour. It does not; it is a *scoring* signal only.
  Home-metro membership comes from `home_metro` + `home_metro_aliases`, never `city_priority`.

**Why the whole contract layer exists:** these formats used to be enforced by prompt instructions, and
prompts are insufficient — a real batch produced a location value with the mandatory `IRL ` prefix
missing. Every contract now has ONE normalizer in `ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/norm_contracts.py`,
applied after model output and before anything is written, tested at the **final artifact** (the actual
spreadsheet cell, the actual filename).

**Three fidelity gaps found in real captures and fixed (with permanent regression fixtures):**

1. **Never company-as-role.** A JS-rendered careers site whose title/og:title/h1 are all site branding
   produced `Company: <X> Careers` / `Role: <X> Careers` and a branding filename. Cleaning the company
   was never enough — a title that slugs to the company, or is pure careers-site branding, is now
   invalid and gets **recovered** from JSON-LD `title` → the page's first heading → the first
   non-navigation heading line of the extracted body text (rejecting nav vocabulary, the employer's own
   name, and JD section headers like "About the role"). If nothing is recoverable the title is a
   **capture failure** (`field_status: title: capture_failed`) surfaced on the capture's Completeness
   line, in the manifest notes, and in a dedicated loud block in the prep report — never an invented or
   branding filename. Recovery runs *before* the older never-role-as-company swap, so a good company
   name is no longer discarded to repair a bad title.
2. **Day ranges were being collapsed.** `2-3 days` normalized to `3 days`, `4-5 days` to `5 days`.
   Silently rewriting a cadence the employer stated is information loss on a field the candidate reads —
   the same fidelity rule that keeps `3 days` distinct from `3+ days`. Ranges are now preserved verbatim
   in the display text and **coloured by the range's maximum** (`2-3` yellow, `4-5` orange).
3. **Multi-city and trailing detail dropped in the `Remote or IRL …` form.** `Remote or IRL A/B -
   unknown days (employer detail)` lost the second office *and* the entire parenthetical. `unknown days`
   now strips as cadence (it had been swallowing the city in front of it), and a trailing parenthetical
   is preserved unless it merely restates the cadence.

Also fixed in passing: HTML comment text could leak into captured job body text via BeautifulSoup's
`get_text()` on both the requests and generic extraction paths. Comments are markup, not job content —
now stripped before extraction.

Docs corrected in the same pass (they contradicted shipped behaviour): `03-VETTING/CLAUDE.md` (the
"never hardcode remote is green" line — this column now hardcodes it deliberately, in exactly one
place; the slash-form Lane examples, which are not valid Lane values; and the false claim that the
`Lane` cell is priority-coloured — that is **Lane Fit**), `docs/v2-end-to-end-workflow.md`,
`docs/testing-and-caveats.md`, and `02-candidate-profile.template.md`. Tests: 328 green
(295 → 328; no golden fixture needed regeneration).


## 2026-07-29 — Posting dates captured (+ a `Posted` rankings column) and canonical apply-URL deep links

Two findings from reviewing a real batch of captures, both decided by her.

**Every ATS publishes a posting date and we discarded all of them.** The only date in a capture was
`Captured:` — OUR fetch date — so nothing downstream could tell a week-old posting from a
nine-month-old one, even though the dates were sitting in payloads we already parse.

- `posted_date` / `updated_date` added to the fetcher result contract (documented in the shape
  comment) and populated per ATS: Greenhouse `first_published` + `updated_at`, Ashby `publishedAt` +
  `updatedAt`, Rippling `createdOn` + `updatedOn`, Workable `published`, Lever `createdAt` (epoch
  MILLISECONDS — the one outlier), and JSON-LD `datePosted` / `dateModified` for generic career
  pages. Workday's `postedOn` is a RELATIVE string ("Posted 30 Days Ago") and is rejected rather
  than converted into a fake date; the CxS payload's real ISO `startDate` is used instead.
- One normalizer, `normalize_posting_date()`, takes all of it to a plain `YYYY-MM-DD` (times and TZ
  offsets stripped, not shifted) and returns None for anything relative, empty, or impossible.
  **Never fabricate:** with no date, the provenance line is omitted entirely.
- Captures gain a `Posted: YYYY-MM-DD` line (plus ` · Updated: <date>` when the ATS exposes a
  distinct edit date); both are recorded in the manifest entry.
- **New `Posted` column** in the rankings CSV/XLSX, placed immediately after `Comp Range` — inside
  the human-scannable block and ahead of the editable `? [You …]` columns, so no existing column
  changes meaning. It is not model output: the norm_contracts pass fills it by reading each row's
  captured `Posted:` line, and `make_rankings_xlsx.py` re-runs the same back-fill on read, so an OLD
  rankings CSV gets the column inserted and populated when regenerated. A value already in the sheet
  is never overwritten. Deliberately a static ISO date, not an age or "days open" number — a
  computed age baked into a saved spreadsheet silently goes stale and starts misleading you.

**A job's apply URL was sometimes a job SEARCH page.** A Greenhouse `absolute_url` is whatever the
employer configured; most are real deep links, but four in the reviewed batch pointed at listing or
search pages that rely on `?gh_jid=` to redirect client-side. Saved as the Application URL, those
open a search later, not the posting.

- Detection is generic, not a host list: the job id is absent from the URL's PATH, present in its
  QUERY, and the path's last segment is a listing-ish one (`jobs` / `search` / `all-jobs` / …).
  When that matches, the Application URL becomes the canonical
  `job-boards.greenhouse.io/<board>/jobs/<id>` deep link and the employer URL is preserved verbatim
  on a new `Employer apply page (verbatim):` line in the archival block — nothing is lost.
- An employer URL that IS a real deep link (the id in the path) is kept exactly as-is, and no other
  ATS is affected.

35 new tests, all against the saved real payloads (including the epoch-milliseconds conversion, the
relative-string rejection, the four listing-page shapes, and the `Posted` column reaching the actual
written spreadsheet cell from a legacy CSV). The golden capture fixture is regenerated for the one
added `Posted:` line.

## 2026-07-29 — Captured-post identity + capture completeness: one normalizer at the prep choke point

Fifth contract. Captured job files are supposed to be named `company-name__job-title.txt`, but the
company was never sanitized, so ONE employer career page produced two different wrong names on two
different fetch routes: the playwright route's `best_company_from_title` used an EXACT-set reject
list, so a `Careers at <Co>` segment passed through as the company (`careers-at-co__role.txt`),
while the requests route's `detect_company` rejected the career-y segment and then fell through to
the ROLE segment, naming the file `role__role.txt`. No wrapper strip existed anywhere in the repo,
and the page's own structured employer name was read and discarded.

- **`normalize_capture_identity(company, title, url, jsonld)`** in `prep_common.py`, invoked at the
  ONE choke point in `process_urls` where the winning fetch result's title/company are read — so
  every route (ATS API / requests / playwright / JSON-LD / embedded-ATS recovery) is normalized
  identically, and it is idempotent per URL. It prefers structured JSON-LD identity, strips company
  wrappers (`Careers at X`, `Jobs at X`, `X Careers`, `X Jobs`) and title site-branding suffixes
  (`- Careers at <Co>`, `| <Co> Careers`, `— <Co> Careers`, trailing employer echo), and NEVER lets
  the role become the company (falls back to the suffix- or domain-derived employer name, and only
  when such an alternative actually exists — it never invents one).
- `best_company_from_title` now rejects branding segments by PATTERN (`\b(careers?|jobs?)\b`)
  instead of exact-set membership.
- **JSON-LD identity threaded through**: `extract_jsonld_jobposting` now also returns
  `hiring_organization` + `title`, carried as `meta["jsonld_identity"]` by both generic fetchers.
  Its return-None criterion is deliberately unchanged so `structured_source` semantics don't shift.
- **Latent bug found and fixed while wiring that up:** `extract_jsonld_jobposting`'s parameter was
  named `html`, shadowing the stdlib `html` module it calls — `html.unescape(...)` raised on the
  str, a bare `except Exception: continue` swallowed it, and the function returned None for EVERY
  page. JSON-LD capture had silently never worked; generic HTML captures were therefore never
  treated as a structured source. Parameter renamed; both callers pass positionally.

Capture-completeness regressions in the same pass:

- **All employer-listed offices preserved.** The prose location scan returned only the FIRST
  `City, ST`, silently dropping the second office; it now collects every distinct one (deduped,
  capped, `"; "`-joined).
- **Third state `Mentioned (no details)`** for benefits/equity, distinct from `Not posted`: a
  posting saying "you may also be eligible for bonus, equity, benefits" HAS told us these exist. The
  same guard stops a comp DISCLAIMER sentence ("the range … does not include equity, bonus and
  benefits") from being surfaced verbatim as the Equity value — a real mis-capture in the golden
  fixture, which is deliberately regenerated in this commit for that one line.
- **The verbatim archive block no longer renders empty quotes** when the employer did publish
  comp/location wording: with no structured field, it falls back to the actual prose LINE the value
  was mined from (including cadence when that line carries one).
- **Deferred prep items from the comp phase, done here:** `ote`/`total comp` removed from the
  BASE-salary keyword list (variable pay is not base pay and must not become the comp value), and
  ALL matching prose ranges are collected instead of just the first (kept machine-readably in
  `field_status`, so multi-zone prose can feed the applicable-bands envelope).
- **`CONFLICTING` is finally reachable.** The status and `[CONFLICT]:` line existed but nothing ever
  populated `compensation_sources` / `location_sources`, so real ATS-vs-prose disagreement was never
  detected. Producers added with a deliberately conservative "materially disagree" bar: DISJOINT
  envelopes for comp (identical or overlapping figures — the common case where a posting repeats its
  range in prose — must not false-flag) and disjoint city sets for location. Both readings are
  preserved machine-readably in the manifest entry, never silently picked.

30 new tests, including a durable fixture reproducing the real career-page shape and asserting the
one correct filename + `Company:`/`Role:` header from every route, through `process_urls` itself.

## 2026-07-29 — Tailored-application names: one canonicalizer replaces four inconsistent instruction sites

Fourth contract into `norm_contracts.py`. Tailored job folders (and the resume-base / cover-letter
filenames that must match them verbatim) were named by FOUR mutually inconsistent prompt
instructions — job-applier.md said `Senior → Sr, VP, Dir`, tailor-jobs.js said `Senior -> Sr, VP`,
cover-letter.js said `Product Manager -> PM, VP`, and 00-job_application_agent.md carried its own
`Sr Analyst / VP Ops / Dir Marketing` examples — so the tailor and cover-letter workflows could
create two different folders for the same job. Now:

- **`canonical_application_role()` / `canonical_application_name()`** in `norm_contracts.py` +
  CLI (`--application-name --company "X" --role "Y"` prints the exact `Company - Canonical Role`
  string; `--application-role` prints just the role). Deliberately narrow rules, per her answers:
  `Product Manager` → `PM` (compounds included; `Chief Product Officer` is not "Product Manager"
  and stays), `Sr`/`Sr.` → `Senior` (NEVER Senior → Sr), `Vice President` → `VP`, `Director` stays
  `Director`, Staff/Principal/Chief + qualifiers preserved verbatim, comma+space inserted between a
  core PM title and a trailing specialization (never removed), an employer `" - "` separator inside
  a title becomes the comma separator, `/` and `:` stripped (filesystem rule). No other rewriting.
  Idempotent, so re-runs land in the same folder.
- **All four instruction sites replaced, not layered over**: agents/workflows now obtain the name
  by running the CLI and use its output verbatim for the folder AND the
  `{{CANDIDATE_NAME}}-Resume - <canonical name>.<ext>` filename (e.g. `Acme - Senior PM, Growth`).
  tailor-jobs.js embeds the fully-filled command (company/role from the rankings pick) in the agent
  prompt; cover-letter.js has the draft agent run the same command and return the canonical
  company/role, which the finalize prompt already interpolates into the .docx/packet names — the
  two workflows can no longer diverge.
- tailor-jobs.js's paste-table reverse-parse now prefers the agent's returned company/role fields
  (folder-name `" - "` splitting, which broke on roles containing " - ", is a last-resort fallback
  only); `company`/`role` added to the tailor confirm schema.
- Tests: the spec's required examples + incorrect-form repair matrix, an idempotency sweep, a real
  CLI invocation test, and a filesystem-layer test (mkdir with the CLI output, exact on-disk name
  asserted).

## 2026-07-29 — Lane contract: bucket renamed "Work Tools" → "Work", taxonomy enforced mechanically

Third contract into `norm_contracts.py`. The Lane bucket set is now **Health / Consumer / Work /
Other** — the vet prompt previously INSTRUCTED "Work Tools", which drifted from the intended
taxonomy. The prompt rule was rewritten (buckets, `Work - Collaboration` / `Work - Productivity` /
`Work - Project Management` / `Work - Legal` / `Work - Consumer Research` examples, 1–2 word
descriptors, reuse-existing-descriptor rule; the exact `Health - Mental Health` rule is retained
verbatim), and the repair now exists in BOTH layers so an old or model-emitted `Work Tools` value
cannot survive into a final artifact:

- `norm_contracts.normalize_lane()` (canonical): `Work Tools - X` → `Work - X`; bare `Work Tools` →
  `Work`; `<Bucket> - <descriptor>` spacing enforced; Mental-Health exact rule preserved. Run by the
  post-scoring CLI pass over the CSV and again by `make_rankings_xlsx.py` on read.
- `normalizeLane()` in vet-jobs.js extended to the same rules (kept in sync; the Python copy wins).
- **Lane Fit is untouched**: the candidate's own priority-lane NAMES are user data (one of them may
  legitimately contain "Work Tools") and never flow through this normalizer — pinned by test.
- Tests: repair matrix + an end-to-end proof that a `Work Tools` Lane value in a CSV is repaired by
  both the CLI pass and XLSX regeneration while the Lane Fit string stays byte-identical.

## 2026-07-29 — Comp Range contract: applicable-bands outer envelope + midpoint Comp Fit rule (resolves the "optimistic green" open question)

Second contract into `norm_contracts.py`, closing the comp question flagged on 7/14 ("a `151-201`
band vs a 180 floor / 200 target painted green because only the high endpoint was evaluated").
Investigation confirmed the label is purely cosmetic — it never feeds the final score, status, or
sort — so this is a color/label-only change with no rescore needed.

- **Prompt (vet-jobs.js `comp_range:`)** rewritten from "lowest-highest across all bands shown" to
  the OUTER ENVELOPE of APPLICABLE bands: include every band covering a way the candidate could
  genuinely take the job (their remote state, an acceptable home-metro office, a configured
  relocation option, unresolved geo/level bands); exclude candidate expectations, bands for
  untakeable locations, unrelated roles, inapplicable levels, and bonus/commission/equity/OTE.
  Endpoints may come from different bands. Never a midpoint, first tier, or model-picked band.
- **`norm_contracts.normalize_comp_range()`** mechanically enforces `N-N` or `??`: repairs `$`, `K`,
  commas, full-dollar figures (`232,000-282,000` → `232-282`), en/em dashes, `to` ranges, and single
  values (`180` → `180-180`); anything unparseable (prose, ambiguous multi-band text) becomes `??`
  WITH a printed warning — never a silently-picked band.
- **`norm_contracts.comp_fit_label()`** implements the approved MIDPOINT rule: red `Below floor` iff
  max < floor; green `Meets/above target` iff midpoint ≥ target; else yellow `Near target`
  (`Unknown` / `No comp prefs` unchanged). This is the single implementation: the post-scoring CLI
  pass re-derives the Comp Fit column from the normalized range (its output wins), and
  `make_rankings_xlsx.py` re-derives it again on read so OLD CSVs regenerate with honest colors.
  The JS `compFitLabel` was updated to the same logic but is only the initial fallback value.
  Comp cells keep the existing green/yellow/red/grey palette (the exact-hex mandate is the
  Working Location column's).
- Tests: repair matrix, midpoint label matrix (e.g. `125-250` vs floor 180/target 200 → yellow now,
  green before), and an XLSX read-back proving a stale optimistic label in an old CSV is corrected
  in the actually-written Comp Range + Comp Fit cells.
- Deferred to the prep-side pass (02-PREP, out of this change's scope): populating
  `compensation_sources` so the CONFLICTING status becomes reachable, prose-miner OTE/total-comp
  exclusion + multi-band collection, and the "Mentioned (no details)" equity/benefits third state.

## 2026-07-29 — Working Location output contract: canonical grammar + exact 4-hex colors, enforced mechanically (SUPERSEDES the 7/14 location-color rule and its 7/29 engine port)

The user issued an authoritative spec for the Working Location column after a real batch proved that
prompt instructions alone can't enforce an output format (a scored row came back as `NYC/SF - 3 days`
with the mandatory `IRL ` prefix missing). Root cause across several recent regressions: formats were
enforced by LLM prompt text instead of deterministic post-processing.

New module `ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/norm_contracts.py` — the single home for output-
contract normalizers (importable + CLI):

- `normalize_working_location(text, cfg)` enforces the canonical grammar — `Remote` ·
  `Remote (<detail>)` · `Remote or IRL <cities> - <cadence>` · `IRL <cities> - <cadence>` ·
  `Unknown`. It inserts the missing `IRL ` prefix, converts `Hybrid X`/`Onsite X` phrasing (onsite =
  5 days ONLY when full-time attendance is established, else `unknown days`), preserves multi-city
  lists (`/`-joined, ordered by configured `city_priority`), preserves exact-vs-open cadence
  (`3 days` ≠ `3+ days`; "at least N" stays `N+ days`), keeps known-city/unknown-cadence as
  `IRL <city> - unknown days`, and assigns `Unknown` only on no signal. Repair-or-fail-loudly: an
  unparseable value becomes `Unknown` WITH a printed warning, never silently. A location requirement
  parsed from an application question normalizes identically to one from the JD.
- `working_location_color(canonical, cfg)` is the ONE deterministic color mapper, returning exactly
  one of four hexes (black text, **no grey**): green `42FF35` = remote genuinely available (never
  inferred from "remote-friendly"/"flexible"); yellow `FDFF43` = acceptable home-metro office at
  EXACTLY 1–3 days; orange `FA9C31` = Unknown, unknown cadence, >3 days, or open-ended minimums;
  red `F82C1F` = required in-person outside the home geography. Home-metro detection uses
  `home_metro_aliases` only — `city_priority` membership does NOT make a city a home metro.
  **Key deltas from the superseded 7/14 rule: exactly-3-days is now YELLOW (was orange), and
  Unknown is ORANGE (was grey); grey is no longer a legal Working Location color.**
- CLI mode `--normalize-rankings-csv <csv> --config jail.config.json` rewrites the column in place,
  printing every repair. `vet-jobs.js` now shells out to it right after writing the rankings CSV,
  before the XLSX build, and its `location:` prompt rule was rewritten around the canonical grammar
  (the prompt is guidance; the normalizer is the contract).
- `make_rankings_xlsx.py` re-normalizes the Working Location cell on read (so regenerating an old
  CSV repairs its text too) and colors BOTH the Working Location and Location Fit cells via the new
  mapper. Deleted the dead `LOC_LABEL_ARR` map; `jail.config.json`'s `location.arrangements` no
  longer influences this color (it remains a practicality-scoring signal).
- New test dir `03-VETTING/tests/`: the spec's full case matrix asserted at the normalizer level AND
  by building a real XLSX and reading the actual written cell fill hex back with openpyxl, including
  the `NYC/SF - 3 days` → `IRL NYC/SF - 3 days` repair and question-derived ≡ JD-derived equivalence.

## 2026-07-29 — REVERT: voluntary diversity-statement prompts are KEPT, not excluded

Reverses the same-day decision to exclude voluntary diversity-statement prompts ("we recruit from underrepresented communities — if you bring a diverse perspective based on your background, share more here"). The candidate reviewed it and reversed the call, and her reasoning is the better rule: **the distinction that matters is FORM, not topic.** A gender/race *dropdown* is a routine self-ID field with nothing to compose — correctly excluded. A *free-text* prompt inviting you to write about your background requires genuinely sitting down and composing something, which is exactly what the "think and compose a response" keep-test is for. Excluding it silently discarded a question she'd actually have to write.

Removed the four narrow patterns from `_EXCLUDE_LABEL_RE` and replaced them with a comment recording the decision and warning against re-adding them (this is the second time the rule has moved; the comment is there so a future pass doesn't "helpfully" re-exclude). Flipped the three parametrized tests from *dropped* to *KEPT*, and added a companion test asserting the revert did NOT weaken the routine exclusions — dropdown-style gender/race/veteran/disability selects must still be dropped. Suite: **129 passed**.

Generic lesson for the filter: when deciding whether a question is "routine," check whether answering it requires composition, not whether its subject matter resembles an EEO topic.

## 2026-07-29 — Multi-ATS application-question capture: three new fetchers + one generalized apply-page renderer

Before this, only two of the supported sources could produce application questions at all: Greenhouse (questions come back on the boards API) and Ashby (questions only exist on the rendered apply page). Every other source hardcoded `"questions": []`, so a whole class of postings looked like they had no questions when they simply had no capture path. Fixed by adding three fetchers and generalizing the render, all in `02-PREP/`.

**New: Rippling** (`ats.rippling.com/<board>/jobs/<uuid>`) — the best of the bunch. Its public board API returns the job content, per-zone pay, work locations, employment type **and** the application questions on one call, so it needs no browser at all. Gotchas worth recording:
- The endpoint 404s with an HTML page unless you send `Accept: application/json`. That's what makes it look like there's no API.
- Its `employmentType` inverts the usual convention: `label` holds the machine token (`SALARIED_FT`) and `id` holds the human string (`Salaried, full-time`).
- The custom questions live at `activeJobApplication.additionalQuestions`, a list of question *sets* each wrapping `form.questions[]`, and it is `null` whenever the employer added none (the common case). Routine fields are a separate `basicQuestions` list; those are fed through the *shared* filter and dropped by name, never special-cased.
- `dataType` is an unreliable compose signal — a long-essay question can carry `dataType: "Text"`. `questionType` (`LONG_ANSWER` / `SHORT_ANSWER` / `KNOCKOUT` / …) is the one to trust. Pinned by a test.
- Non-annual pay frequency is preserved: an hourly band read as an annual salary would be a catastrophic mis-score.

**New: Workable** (`apply.workable.com/<sub>/j/<CODE>`) — the accounts/jobs API gives content, all locations, workplace type and employment type, plus a clean company display name from the account record (the subdomain alone reads wrong). It carries **no** questions and usually a null salary, so questions come from rendering the apply page.

**New: Workday** (`<tenant>.wdN.myworkdayjobs.com`) — previously unsupported because the CxS API needs a `Job_Posting_Site_ID` that's widely treated as undiscoverable. It isn't: **it is simply the first non-locale path segment of the public job URL** (`.../WG/job/...` → site id `WG`). Guessing the company name instead 404s with `not found: Job_Posting_Site_ID=<name>`. Verified against two unrelated tenants. Workday gives content / location / employment type / hiring-organization name, but **no pay and no questions** — the payload exposes only a `questionnaireId`, and the questionnaire itself is behind candidate auth. Recorded as genuinely absent rather than as a capture failure. Also fixed the company derivation for these hosts: the org is the tenant *subdomain*, while the first path segment is the posting site id, which was previously being written out as the hiring company.

**Extended: Lever** — the postings API has no questions field but does carry `applyUrl`, so Lever now gets questions the same way Ashby does.

**Generalized the render instead of copy-pasting it per ATS.** `_render_ashby_questions` was Ashby-named but its DOM scrape (labeled field container → title / type / options / required) was already generic. It's now `render_apply_questions`, with a small per-ATS apply-URL builder table and a single shared field-scrape. Ashby / Lever / Workable / Homerun all route through it; Greenhouse and Rippling deliberately do not, since rendering an ATS whose API already carries the questions is pure cost. Two real bugs surfaced while generalizing:
- The label container is sometimes a bare `<label>` whose control is the `for=` target or an adjacent sibling rather than a descendant. The old scrape only looked *inside* the container, so essay textareas were misread as plain text inputs and then dropped as non-compose. Now it checks `for=`, next sibling, and parent.
- Some forms mark required-ness only visually (a trailing asterisk, no `required` attribute), and rendered containers also pick up the select's own option text and file-input chrome inside the label. Added `clean_apply_label`, which strips required-marker glyphs (reporting `required` from them), drops option/chrome lines, and collapses the rest.

**Also fixed** the host-only Ashby check left behind in the Playwright fetcher — the primary fetcher had already been corrected to detect by host **or** `ashby_jid=` **or** an ATS-ish `source`, but the render path still tested the host alone, so custom-domain jobs skipped question capture there. Both paths now share one `detect_apply_ats` helper. It matches URLs on **host only** so a role slug can't masquerade as an ATS (a "clever-…" title is not Lever), and matches `source` labels as substrings, which is how custom-domain jobs get identified at all. The render's best-effort `except` still **prints** the exception rather than swallowing it — a silent except is what previously let a broken URL builder masquerade as "this job has no questions" — and an ATS with no job API at all now also gets an apply-page render from the plain-HTML path, since its job page never reaches the ATS branch.

**Filter additions** (narrow, same rationale as the diversity-prompt exclusion): routine free-text fields that the compose-a-response keep-rule would otherwise retain even though they're administrative and say nothing about the job — "where are you based", "where did you find out about / how did you hear about this role", and interview-accommodation requests.

**Investigated, not implemented: Homerun.** Its `/api/jobs` returns HTTP 200 but serves the page HTML, not JSON — the host answers every path with the same shell, so a 200 there means nothing. Its `application/ld+json` block is literally `{}`. There is no clean job-by-id endpoint, so there's no Homerun *fetcher*; the job page is plain server-rendered HTML that the existing generic path already reads, and its **questions do now get captured** via the generalized apply-page render.

Durable offline fixtures (real saved API payloads, no network in tests) added for Rippling (including the `additionalQuestions: null` case, which must yield zero kept questions without crashing), Workable, Workday, and Lever. Suite: **67 → 128 passed**.

## 2026-07-29 — Question filter: exclude voluntary diversity-statement prompts

Found while replacing an aggregator-sourced capture with the employer's own ATS post: the newly-visible application questions included an optional "we recruit from underrepresented communities — if you bring a diverse perspective based on your background, share more here" prompt, and the narrow filter KEPT it. The exclusion regex covered `self-identif` / `demographic` / the explicit gender/race/veteran/disability terms, but not this phrasing.

These prompts are free-text, so the compose-a-response keep-rule retains them by default — yet they are candidate **self-identification**: they reveal nothing about the job and aren't a job-specific response, so they fail both keep-tests and belong with the rest of the excluded EEO/identity set. Added narrow patterns (`underrepresented communit|group|background`, `diverse perspective`, `diversity of our team`, `advancing the diversity`), deliberately scoped so a genuine job-material question that happens to mention diverse USERS still survives — pinned by a test asserting exactly that ("how would you design onboarding for a diverse set of users" is KEPT). Suite: **67 passed**.

Also of note for the aggregator-vs-source question generally: re-fetching the same posting from the employer's own ATS rather than a job-board aggregator yielded identical JD prose but added the application questions and a canonical apply URL — aggregator captures silently lack the application form. Prefer the employer/ATS URL when both exist.

## 2026-07-29 — Ashby application-question capture was broken for ~every real URL (query-string bug); silent-except hid it

The user spotted that two jobs reported "(none kept)" for application questions when both plainly have one — including the very posting used as the Ashby calibration example when this feature was built. Root cause was NOT the DOM scraper or the narrow filter (both verified working when given a correct URL); it was apply-URL construction in `_render_ashby_questions`:

```
url.rstrip("/") + "/application"
```

For any job URL carrying a query string this produced `.../<id>?src=LinkedIn/application` — `/application` landed AFTER the query string, the apply page never loaded, and the `except Exception: return []` swallowed it into a silent "no questions". Real URLs from LinkedIn/job boards essentially always carry `?src=` / `?departmentId=` / `?utm_source=`, so question capture was failing for nearly every Ashby job in practice — while the test suite passed because **every existing test used a clean, query-less URL.** Classic false-confidence: the one case the tests covered was the one case that worked.

Fixes (all in `02-PREP/`):
- New `ashby_apply_url()` builds the apply URL from the parsed PATH only (drops query + fragment), and is idempotent when the path already ends in `/application`.
- `_render_ashby_questions()` now accepts an `apply_url_hint` and prefers the **ATS-provided** `applyUrl`. This is canonical and additionally fixes a second, independent gap: **custom-domain Ashby** jobs (e.g. `lark.com/careers?ashby_jid=<uuid>`) whose own host/path can't be turned into an apply URL at all.
- `fetch_one()` now detects Ashby by SOURCE (`ashbyhq.com` host **or** `ashby_jid=` param **or** an ashby-ish `source`), not host alone — custom-domain Ashby jobs previously skipped question capture entirely.
- The best-effort `except` now PRINTS the exception type/message instead of failing silently. The fully-silent except is what let a signature/selector break masquerade as "this job has no questions"; a surfaced warning would have caught this immediately.
- Tests: added a parametrized regression suite for apply-URL construction covering single/multiple query params, utm params, fragments, trailing slashes, and already-`/application` URLs (with and without a query string), plus an assertion that `/application` never appears after a `?`. Also fixed the existing always-render test, whose single-arg stub renderer was masking the new signature via the same silent except. Suite: **63 passed**.

Re-fetched every Ashby-sourced post in the active review folder with `--force`; question capture now populates correctly (compose-a-response essays and office-cadence questions both come through). Verified the remaining zero-question posts are legitimately zero — those postings expose only routine/identity/EEO fields (name/email/resume/LinkedIn/website/phone/current-location/sponsorship/gender/race/veteran), all of which the narrow filter is specified to exclude. This also corrected an earlier *over*-capture, where one post had listed several "questions" that were all routine fields (i.e. unfiltered).

**Generic lesson worth keeping:** a test fixture set that only covers canonical/clean inputs can pass while the feature is broken for the input shape users actually have. Prefer fixtures drawn from real-world URLs (with tracking params and all), and never let a best-effort `except` degrade silently on a path whose empty result is indistinguishable from a legitimate empty result.

## 2026-07-29 — CLAUDE.md: durable Git checkpoint policy for all coding agents

Added a "Git checkpoint policy (required)" section to `CLAUDE.md`, right after the changelog rule. Prompted by this session, where large amounts of completed engine work (prep completeness, rescore tooling) accumulated in the working tree across many turns before being committed — the user had to notice and checkpoint it herself. The rule makes checkpointing a completion requirement, not an afterthought: meaningful work isn't done until verified, changelogged, committed, and pushed. It codifies begin-task repo inspection (never mix/overwrite pre-existing user work), one-coherent-task-per-commit, before-commit checks (tests, `git diff --check`, stage only the task's files, run the privacy firewall, changelog-accuracy check, don't claim "shipped" without the implementation in the commit), commit+push the normal branch (never force-push, don't let a dirty tree accumulate), explicit exceptions (user opt-out, don't commit failing work to look clean, read-only work needs no commit), and a required per-task completion report (checks, changelog, commit hash+message, pushed?, tree clean?, any intentionally-uncommitted files). Reinforces the existing privacy rules (no candidate data/strategy/scores in the public changelog; no firewall override without explicit user approval of a reviewed false positive).

## 2026-07-29 — Completeness audit of 51 still-open jobs surfaced a real working-location prose bug

Ran a private completeness audit: re-fetched 51 still-open jobs with the current engine and compared each result with the text originally scored. Three were materially incomplete or employer-changed, three were now closed, and the other 45 retained complete job text. Re-scoring the affected usable posts confirmed that truncated responsibilities can materially change rankings even when comp/location were present. One SPA career-site family also re-fetched worse than the originals because related-jobs chrome contaminated the captured body; preserve the originals until a dedicated cleaner ships. Candidate-specific companies, scores, and artifacts remain in the gitignored audit folder rather than this public changelog.

**Bug found — working-location prose fallback declared `found` on garbage.** Among audit jobs whose working location came from prose, four captured the literal single letter `"s"` and three more returned noisy navigation or marketing text while still reporting `Completeness ✓`. The comp prose scanner was clean on the same audit. The false-complete condition was isolated to the location prose regex; structured-ATS captures were unaffected.

**Fix shipped (`prep_common.py`).** Two root causes, both in the location prose path (comp path untouched; structured-ATS path untouched):
1. `_LOC_LABEL_RE` matched the keyword "location" *inside* the plural nav label "Locations"/"Office locations" and captured the trailing `"s"` — fixed by `\b`-terminating the keyword group.
2. `_CITY_STATE_RE` used `\s` as its inter-word separator, and `\s` matches newlines, so a city glued onto the previous line's trailing token across a break ("Google Cloud\nAustin, TX" captured as one city) — fixed by restricting the separator to `[ \t]`.
New `_sanitize_location()` validates every prose candidate before the gate may call working-location `found`: prefer a real `City, ST`, drop division prefixes / trailing marketing-sentence+URL tails, reject sub-3-char/nav-blocklist tokens, and require a genuine workplace signal (Remote/hybrid/onsite/cadence) or a compact "City, Region" phrase — else `None` → `capture_failed`. Verified against the audit's malformed values, including rejection of `"s"` and cleanup of navigation text joined across a newline. Added 15 regression tests (section 19 in `02-PREP/tests/test_prep.py`); suite now 54 passing. **Still open (secondary, not done):** one SPA career-site family pulls related-jobs chrome into the body and needs a dedicated extraction fix.

**Also caught (process note):** the first-pass audit diff compared only the job *body* and stripped the `== NORMALIZED ==` block, which made correctly captured compensation look missing. Any completeness comparison must read the normalized block, not just the body.

## 2026-07-29 — Desire: add bounded "Strategic Career Leverage" factor (stepping-stone value)

Fixes a real Desire blind spot: a role can be only moderately attractive *in isolation* yet highly worth limited application time because succeeding in it would build the specific, missing evidence that makes the candidate much more competitive for the work they ultimately want next. That is NOT Profile Fit (how a hiring team sees the documented profile now) — it's a distinct question the sub-factor sum missed.

Smallest clean change (no redesign, no new column/score, Desire weight/format unchanged): replaced the vague "career-ladder value" cross-cutting multiplier with a rigorous, bounded **Strategic Career Leverage** rule that mirrors the existing mission-floor override pattern — `desire = max(sum, min(sum + uplift, 85))`.
- **Gated by a 3-part test** (all must hold for Strong/Exceptional): named-gap (closes a *stated* strategic gap), ownership (the work is the candidate's *actual mandate*, not "the company uses AI / is in healthcare / another team owns it"), future-legibility (a target-lane employer would readily understand the evidence).
- **Bounded uplift:** None +0 / Some +2–6 / Strong +7–11 / Exceptional +11–16, capped at 85 (leverage alone never makes a role a drop-everything 86–100 dream), never lowers the raw sum, disliked-work guard (Role Excitement ≤ 10 → capped at Some), and it never touches Profile/Style/Practicality. Explicitly must not reward prestige/logo/comp alone, vague AI/health adjacency, or paths needing unsupported leaps. Output stays concise — one clause in `mission_fit_notes` + level/evidence in the optional `mission_fit_detail`; no new column.
- **User-defined, generic:** driven by three new candidate-profile fields (`Target Career Direction`, `Primary Strategic Gaps`, `High-Leverage Bridge Work`); if blank, NO adjustment is applied (never invent a strategy). Added to the public `02-candidate-profile.template.md` (optional/lightweight) + `01-scoring-card.template.md` (generic explanation with the "helps decide where to spend application effort" framing), with a scorer pointer in `vet-jobs.js`. Candidate-specific values and calibration results remain in gitignored private files.

## 2026-07-29 — Rankings: visible per-job "Data Completeness" column + loud top-of-sheet flag

Prep now records per-field capture quality (comp + working-location), but nothing surfaced it in the ranking — so the candidate couldn't tell at a glance which scores were computed against complete data without spot-checking each job. Added a generic (all-users) Data Completeness indicator threaded through both halves of the rankings output:

- **`vet-jobs.js`:** new `Data Completeness` column in `HEADERS`/`dataCells` (after Comp Fit, before Cover Letter?). Value derived deterministically at assembly time (no LLM, no `SCORE_SCHEMA` change): read the prep manifest once (`0 - Prep Report/prep-manifest.json`), map `basename(output_path)` → `field_status`, and label from it — `✓ complete` when both comp + working-location are `found`; else a terse flag distinguishing benign employer omission (`comp not posted`) from could-not-verify (`⚠ comp not verified` / `⚠ location unknown` / `⚠ comp+location not verified`). FALLBACK for older batches with no `field_status`: derive from the row's own comp/location text (comp `??`/empty or location `Unknown`/empty → could-not-verify). A loud summary line was also added to the top of the Markdown rankings: `⚠️ Incomplete captures (N): …` (attention rows only; skips pure `not posted`), or an all-clear line.
- **`make_rankings_xlsx.py`:** maps the label text → a cell color (green `complete` / amber `not posted` / red could-not-verify), and — for CSVs written before this column existed — reproduces the JS row-fallback so any batch regenerates with the column populated + colored. Added a merged banner just below the jobs (above the section legend) carrying the same `⚠️ Incomplete captures (N)` list, and mirrored the flag at the top of the Instructions tab. Column-index/letter mapping stays dynamic off the CSV header, so the inserted column needed no manual re-indexing of widths / dropdown / autofilter ranges.

Verified by regenerating a pre-`field_status` batch from its current CSV, exercising the fallback: three `Unknown`-location rows became `⚠ location unknown` (red), the remaining rows became `✓ complete` (green), and the banner listed the three affected rows. The XLSX reloads clean via openpyxl; the prep pytest suite remained green.

---

## 2026-07-29 — Prep completeness: prose-aware verdict + custom-domain ATS dispatch (stop crying wolf)

Re-verifying the whole 07-28-26 batch (11 jobs) with the new engine exposed two false-alarm classes: 6 jobs came back `capture_failed` for comp+location even though several plainly published them — Rippling, Blue Rose (techjobsforgood), and the Google roles write the pay range and location into the JD PROSE, and the vetting scorer reads that body and used them correctly. The completeness verdict was only checking structured fields, so it contradicted what the scorer could actually determine. Two fixes, both in `02-PREP/`:

- **FIX 1 — prose-aware `assess_completeness` (prep_common.py).** Before marking compensation or working-location `capture_failed`, scan the captured JD body (the same text the scorer reads): a currency/keyword-gated pay range (`$174,000 - $290,000`, `USD 232,000–282,000`, `$110K–$180K`, and comma-less currency amounts like Google's `$240000 - $334000`) → comp `found` (source: description), best-effort range surfaced on the Compensation line marked "(from description)"; a named `City, ST` / Remote / hybrid-cadence / `Location:` line → working-location `found` (source: description). Only falls through to `capture_failed` when the field is absent from BOTH structured sources AND the prose. Non-salary numeric ranges ("20-50 employees", "2019 - 2023") are rejected by requiring a currency marker or salary keyword.
- **FIX 2 — custom-domain ATS dispatch (ats_fetchers.py).** A non-ATS host carrying an ATS id in its query is now routed to that ATS: `?ashby_jid=<uuid>` → Ashby (org guessed from the domain via brand-suffix stripping; matched by the globally-unique UUID against the org's board feed — this rescued `lark.com/careers?ashby_jid=...`, which otherwise captured only a cookie banner); `?gh_jid=<digits>` → the existing embedded-Greenhouse recovery, now with improved board-token derivation (`pinterestcareers.com` → `pinterest`) and a URL-path role-slug added to the title-match safety guard, so a correct board hit passes even when the fetched page is a thin shell with no usable title/body (this recovered Pinterest).

Re-verification result (11 URLs; the batch file has 11, not 12): **10/11 now fully recover comp+location** across structured ATS, custom-domain ATS-id recovery, and prose fallbacks. The one holdout rendered only a generic SPA navigation shell, so `capture_failed` is the truthful result. Tests: 39 passed (added prose-comp variants including comma-less currency, prose-location city/remote + no-false-positive, custom-domain ATS dispatch + no-match, and slug-matched embedded-board recovery).

## 2026-07-29 — Prep completeness: fix `not_posted` vs `capture_failed`, add embedded-Greenhouse recovery, trim doubled question quote

Live smoke test on `careers.airbnb.com/positions/8044715/` surfaced a correctness bug in the completeness gate shipped earlier today: a generic (non-ATS) HTML scrape that found no comp and no location marked BOTH as `not_posted` — the exact failure the feature exists to prevent (Airbnb's $232K–$282K pay and SF/NY location ARE published; that job is actually served by Greenhouse board `airbnb`). Fixes, all in `02-PREP/`:

- **Status logic (`assess_completeness`, `prep_common.py`):** a field is `not_posted` ONLY when a *structured* source was consulted and the field is genuinely absent (ATS API with empty `pay_input_ranges`, Ashby `shouldDisplayCompensationOnJobPostings=false`, or JSON-LD with no such field). A field missing from a bare generic/non-structured HTML scrape is now `capture_failed` (could-not-verify), which is what arms the field-driven retry cascade. New `_source_is_structured(meta)` helper + explicit `structured_source` flag threaded through the fetchers (ATS/JSON-LD → structured; plain `requests/html`/`playwright/html` with no JSON-LD → not).
- **Embedded-Greenhouse recovery** added to the retry cascade: when a non-ATS career URL carries a Greenhouse-style numeric job id in its path (or the HTML references `boards.greenhouse.io`/`gh_jid`), prep now tries `boards-api.greenhouse.io/v1/boards/<token>/jobs/<id>` with board tokens derived from the domain (`careers.airbnb.com`→`airbnb`). SAFETY guard: a domain-guessed token's result is accepted only when its job title reasonably matches the page title we already have, or its title words appear in the fetched body — so a wrong board that merely has a job with the same numeric id is discarded. This recovered Airbnb comp+location live (status `not_posted`/`not_posted` → `found`/`found`, method chain `requests → playwright → greenhouse-embedded`).
- **Polish:** verbatim application-question labels that already end in a stray double-quote no longer render a doubled trailing quote (the Bloomerang question-2 `…delivery?""` bug) — `_strip_wrapping_quotes` trims wrapping double-quotes before we wrap the label in our own.
- **Coverage:** added pytest cases — generic scrape with no comp/location → `capture_failed` (not `not_posted`) and fires the fallback; structured scrape absent field → `not_posted`; embedded-GH recovery recovers comp/location, guards a wrong board, and no-ops (no network) when there's no GH id; and the doubled-quote polish. Suite: 27 passed.
- **Ashby questions always rendered on the primary pass:** Ashby's posting-api ALWAYS returns comp/location but NEVER returns questions — so a normal requests-first Ashby run was "complete" (comp/location found), no fallback fired, and the thoughtful questions (e.g. BetterUp's mission essay + office-cadence) were never captured. Fix: for Ashby jobs only, the primary `fetch_one` now always attempts the best-effort Playwright apply-page render (`_render_ashby_questions`) and merges the filtered questions into the posting-api meta WITHOUT re-fetching comp/location. Graceful (try/except → `[]`; never fails the fetch, e.g. Playwright absent). Non-Ashby jobs never invoke it, so the requests-first fast path is unchanged for them. Live-verified on the BetterUp URL: on a clean run (`methods_tried: ['ats']`, no fallback) the 2 kept questions now appear where the block was previously "(none kept)". Added 3 tests (always-render-even-when-API-complete merge; graceful degradation on render failure; Ashby-only gating). Suite: 30 passed.

## 2026-07-29 — Prep completeness gate: comp/location verified & recovered BEFORE ranking; provenance; thoughtful-question capture

Root problem the user hit repeatedly: comp or working-location was missing from saved job captures ~25% of the time even when the posting plainly published it (Lark's salary lived only in Ashby's structured comp field and was dropped; Airbnb's pay range was never captured), which corrupts rankings (comp/practicality scored against `??`) and forces a manual re-fetch + re-rank. Root causes: prep only guarded against *thin* bodies (never verified specific fields), ATS results bypassed validation entirely, and the rich structured fields the fetchers already pulled were flattened away before write.

Built a completeness-and-recovery gate that runs in prep, BEFORE ranking (all in `ENGINE__PUBLIC_GIT_TRACKED/02-PREP/`, kept PII-free — no jail.config reads):
- **Enriched extraction** so comp/location are actually captured: Ashby now reads per-zone `compensationTiers`, `secondaryLocations`, `address`, `workplaceType`; Greenhouse uses `?questions=true&pay_transparency=true` + `pay_input_ranges`/`offices` (was hardcoding comp=None); Lever gains workplace/location; benefits/equity use best-effort description-prose extraction. The full structured meta is now threaded through `fetch_one` instead of flattened to title/company/body. **Known soft-field limitation:** brief prose mentions such as “eligible for equity and benefits” may still fail to populate the normalized soft fields even though the full body preserves the statement.
- **`assess_completeness`** → per-field status `found` / `not_posted` / `capture_failed` / `conflicting` for compensation + working-location (+ title/description). Key discipline: a comp/location *question* is not the job *fact* — "compensation expectations?" ≠ employer comp, "where do you live?" ≠ working location, but an office-attendance requirement DOES supply working-location + cadence. A generic/non-structured scrape that finds nothing is `capture_failed` (retryable), NOT `not_posted`.
- **Field-driven retry cascade** (extends the old thin-body fallback): missing/uncertain comp or location triggers structured-ATS → rendered page → apply page → an embedded-Greenhouse recovery (custom career domains like `careers.airbnb.com` that are Greenhouse-backed) before giving up. Still missing after the cascade → flag loudly (prep report "⚠️ Incomplete captures" + manifest `field_status`/`missing_fields`/`methods_tried`) and **rank anyway** — never quarantine for a missing field.
- **Dual-preservation `.txt` layout** (normalized never replaces source): provenance line (capture date, source, posting id, urls, methods tried) + a NORMALIZED block (Working Location / Compensation / Benefits / Equity each status-tagged, a Completeness line, `[CONFLICT]` when sources disagree) + employer-provided structured wording when available + the full description between the existing markers. **Known generic-fallback limitation:** prose-derived values can appear in the normalized block while the separate structured-source lines remain empty; the full body is still the durable source.
- **Thoughtful-question capture (narrow):** Greenhouse via `?questions=true`; Ashby/others via best-effort Playwright apply-page render. Keep a question ONLY if it's a compose-a-response essay OR reveals job location/cadence/employer-comp; exclude all routine/identity/EEO + work-auth/visa/comp-expectations. Verified: Bloomerang→3 essays, BetterUp→mission essay + office-cadence question (the latter also feeds Working Location, preserving the full employer metro list; candidate-relative mapping happens at vetting, not prep). Kept verbatim (text, help text, choices, required flag).
- **Durable fixtures + pytest** under `02-PREP/tests/` (Bloomerang GH + BetterUp Ashby responses + a hand-authored rendered-apply-form fixture) so this is regression-tested offline, not only against live pages that will disappear.

Downstream wiring: `vet-jobs.js` scoring prompt now treats the NORMALIZED `Compensation:` / `Working Location:` lines as authoritative (parse comp from `[found]`; `[not posted]`→`??`; `[capture_failed]`/`[conflicting]`→`??` + note), and computes the candidate-relative location by matching the candidate's home-metro/`city_priority` against the employer metro list + applying the office cadence (e.g. a NYC user gets `IRL NYC - 2 days` from the BetterUp office question) — generic, not hardcoded. Tailor spec (`04-TAILOR/00-job_application_agent.md`) flips application-answer drafting from out-of-scope to narrowly in-scope: a new "Proposed Answers to Application Questions" section drafts lightweight best-effort answers for the compose-a-response questions only, in the candidate's voice from existing canon, deferring uncertainties to "Questions for the candidate" (never blocking; no routine/work-auth/comp-expectation answers).

Follow-ons still open: best-effort Lever/Workday/LinkedIn question capture (LinkedIn's guest API exposes no form). Ashby question capture remains best-effort, but the later primary-pass fix above means it is attempted even when the posting API already supplied complete comp/location.


## 2026-07-29 — Working-location day-count coloring ported; structured comp gaps fixed; lane calibration reviewed

Three issues surfaced during review of a private batch:

**1. Working Location column was all one green.** The user's documented location-color rule (Remote→green; home-metro 1–2 days→yellow; home-metro 3+/unclear/multi-hub→orange; non-home-metro→red) was only ever applied in a 7/14 one-off rescore workbook — it was **never wired into the shared engine**, and the 7/14 changelog wrongly claimed "the real engine already does this correctly." It did not: `make_rankings_xlsx.py`'s `loc_color` colored purely by arrangement TYPE via the config rating (`home_hybrid: "preferred"` = green), with **no day-count sensitivity**, so every NYC-hybrid role (1 day or 5) painted green. Fix: rewrote `loc_color(workloc, label, cfg)` to derive the day count from the Working Location text and apply the documented rule; updated the one call site. Verified on the batch: NYC 3-day/unclear now orange, remote green, unknown grey. This supersedes the pure arrangement-rating lookup (the config's per-arrangement ratings no longer drive the color; day count + home/other classification do). Subjective color choice — user can adjust the mapping.

**2. Two roles returned `??` even though both postings listed compensation.** This was a fetch-completeness gap, not a scoring-agent error: one range lived only in a structured ATS compensation field, while another was present in Greenhouse JSON but absent from the captured body. Both were recovered and persisted. **Lesson for prep:** explicitly capture structured compensation; a description-only fetch can miss pay that renders on the live posting.

**3. A civic/social-impact role was mis-laned as generic political technology.** Private candidate-specific lane and score corrections stayed in the gitignored output. The generic lesson is that explicit democracy/civic/social-impact language should not be flattened into an `Other` bucket, and a technical qualification expressly framed as learnable should not automatically become a hard day-one gate.


## 2026-07-28 — Vetting regression fix: SCORE_SCHEMA too large for the platform safety classifier

The 07-28-26 vet batch failed with all 11 scoring agents erroring identically: "blocked by safety
classifier: output schema too large to classify safely." The two setup agents (discover, refs)
succeeded; only the `Score` agents — the ones passing `SCORE_SCHEMA` — failed. Cause: the platform now
runs a safety classifier over structured-output schemas and rejects ones past a size threshold, and
`SCORE_SCHEMA` in `.claude/workflows/vet-jobs.js` had grown very large — the `location` and `lane`
field descriptions were ~1.4KB and ~1.3KB respectively, plus long example-laden `mission_fit_notes` /
`scope_fit_notes` descriptions. This is an environment change surfacing as a regression; the workflow
itself was unchanged.

Fix: stripped `SCORE_SCHEMA` field descriptions down to bare types (kept only the `confidence` enum and
the integer min/max bounds). No guidance was lost — every one of those rules is already stated in full
in the scoring *prompt* ("Scoring rules" bullets), which is the real instruction source; the schema
descriptions were redundant copies. Added a header comment warning future editors to keep the schema
terse and put new detailed guidance in the prompt, not the schema.

Two-part gotcha worth remembering for next time this recurs:
1. An intermediate trim (short one-liner descriptions) still failed identically — the classifier
   threshold is low enough that only a near-empty schema clears it. Go straight to bare types.
2. Re-running via the `run-batch` front door kept failing even after the file was fixed on disk,
   because `run-batch` reaches `vet-jobs` through `workflow('vet-jobs')` and the workflow registry
   had cached `vet-jobs` at session start — it never re-read the edited file. Running `vet-jobs.js`
   directly via `Workflow({scriptPath: '.../vet-jobs.js'})` bypassed the cache and picked up the fix.
   (Caveat learned: pass that direct invocation's `args` as real JSON — unquoted keys like
   `{folder: ...}` fail `JSON.parse`, so `outDir`/`batchName` silently drop and the outputs land in
   the source folder with the wrong name; had to move/rename them into `1 - Rankings/` by hand.)

## 2026-07-28 — Prep recovery: Cloudflare + cookie-banner pages need ATS-API fallback beyond Playwright

Ran a fresh 11-URL batch (07-28-26). Two posts came back unusable and neither requests nor the
Playwright renderer could recover them, but both had ATS IDs in the URL that let me fetch clean JSON
directly:
- Pinterest (Sr PM, Core Saving Experience) — Cloudflare "Just a moment" challenge blocked both
  requests and Playwright; recovered via the Greenhouse boards API using the `gh_jid` (board token
  `pinterest`): `https://boards-api.greenhouse.io/v1/boards/pinterest/jobs/<gh_jid>`.
- Lark Health (Senior PM, AI Coaching) — the `lark.com/careers/open-positions?ashby_jid=…` page
  fetched *above* the thin threshold (~1.9KB) but was pure cookie-consent boilerplate, so it passed
  as "usable" while containing no job text. Recovered via the Ashby posting API
  (`https://api.ashbyhq.com/posting-api/job-board/lark?includeCompensation=true`, needs a browser
  UA header or it 403s) and matched on the `ashby_jid`.

Takeaway worth noting for the prep engine: (1) a size-only thin check misses cookie-banner/consent
pages that clear the byte threshold with zero real content — a content check (or detecting known
banner boilerplate) would catch these; (2) when a URL carries a `gh_jid`/`ashby_jid`/etc., the ATS
JSON API is a more reliable recovery path than re-rendering the anti-bot HTML page. `ats_fetchers.py`
already does ATS-first for some hosts, but these two slipped through to the HTML path. No engine code
changed yet — captured here as the pattern to fold in.

## 2026-07-17 — Cover letters: never overwrite an original; every revision is a new version

A requested cover-letter v2 overwrote the original run's `final.md`, `.docx`, and review packet,
destroying the church-and-state learning baseline (reconcile diffs the agent's ORIGINAL against the
submitted PDF; overwriting the original erases that signal). Hard rule now, for every user. The
original private artifacts were restored and later drafts separated into versions.

Enforcement added in three tracked places so the workflow can't do this again:
- `cover-letter.js` finalize stage: a versioning guard — if `_cl_work/final.md` already exists, write
  this run's outputs to `final-v2.md` / `… - v2.docx` / `… - v2.md` and leave the originals
  byte-for-byte untouched; only create un-versioned originals when none exist.
- `.claude/agents/cover-letter-writer.md`: added a "Church-and-state: never overwrite an original"
  section with the same versioning rule, applied before any DRAFT/REVISE work.
- `formatting-spec.template.md` (+ the private live instance): church-and-state section now carries the
  "new letters are new versions, never a clobber" corollary.

---

## 2026-07-17 — tailor-jobs / cover-letter always return a paste-ready table now

Root cause from a backlog run: the rankings writeback (added 7/16) only lands when the job's batch has
a rankings file. A job tailored outside a current batch had nowhere for its base to go, so the result
existed only inside its per-job output instead of a paste-ready tracker table.

Considered and rejected a bigger fix (teach the writeback to scan every historical batch by URL and
backfill archived rankings). The smaller, more honest fix was to make the paste-ready result
unconditional:

- `tailor-jobs.js` / `cover-letter.js` now UNCONDITIONALLY return a markdown `table` field (Company
  · Role · Base Resume Used, or Company · Role · Cover Letter?) — independent of whether the
  Record-phase writeback found a rankings row to update. This is what actually gets pasted into a
  user's tracker; it must not depend on a rankings file existing.
- Added `terseBase()` in JS mirroring `update_rankings_row.py`'s `terse_base()` (Python), verified
  byte-identical output across every real example from this session. Two implementations, same
  behavior — worth revisiting if they drift; noted here for whoever touches the Python one next.
- Per-batch writeback behavior UNCHANGED — still fires when a rankings file exists for the job's
  batch (the normal same-day vet+tailor flow), so nothing regresses there.

---

## 2026-07-17 — `terse_base()` normalizer: handle bare dates and dates with extra words in the paren

Found while tailoring a backlog: `update_rankings_row.py`'s `terse_base()` wrote two bases
through un-normalized because its date anchor only matched a date fully inside parens with nothing
else. Fixes: (1) collapse `(7/1/26 finalized submission)` → `(7/1/26)` before anchoring; (2) when a
base has a BARE date and no clean parenthesized one, truncate right after the bare date instead of
latching onto a later non-date paren. The affected private rows were corrected by re-running the
writeback.

---

## 2026-07-16 — Reconcile gap found: a failed agent's findings can be silently lost (worked around by hand; not yet fixed)

During the 07-16 reconcile batch, the Paperless Post agent wrote its reconcile report to the folder but
then failed its structured-output return (retry cap), so the Synthesize stage never received its
findings — no ledger entry, no queue items, no anecdote harvest. A follow-up run then skipped the folder
as "already reconciled" because discovery treats report-presence as done. Findings were merged by hand
this time (ledger entry, anecdote `habitual-gathering-host`, annotations). Real fix for later: discovery
should verify the folder is represented in the ledger (not just that a report file exists), or the
per-folder agent should only write its report after a successful return.

## 2026-07-16 — Tailor-output usability overhaul from Bloomerang reconcile feedback (engine half)

User feedback after completing the Bloomerang application, split explicitly (at her request, with sign-off)
into user-specific lessons (routed through /reconcile into her learning ledger/queue) and engine changes
for every user. The engine half, all in `04-TAILOR/00-job_application_agent.md` unless noted:

- **"Questions for the candidate" discipline:** the section is for genuine work-history/experience gaps
  whose answers change the resume. Comp FYIs move to Final Risks/Notes; "reminder: this optional section
  is optional" boilerplate is banned outright (the recurring Content Opportunity disclaimer was appearing
  in output after output). Flagging a genuinely NEW bullet for confirmation stays — that's the section's
  actual job.
- **Delta-only output against the chosen base:** unchanged role sections are now ONE line ("No changes —
  use [base]'s section as-is"), never restated bullets; the file reads as a change list, not a resume
  transcript. Trigger: outputs had ballooned to where finding the real edits took longer than making
  them (e.g. "replace X with Y" where Y was word-for-word identical to the base's X).
- **Summary rule (generic version, per her approval):** don't spend summary space duplicating what's
  visible in the first experience bullet — summary sells role fit. (Her stricter Ascend-specific version
  goes in her private files via reconcile.)
- **Content Opportunity is now an intake opt-in** (intake SKILL.md Step 5 + spec Step 9.5): intake asks;
  decliners never see the section; opt-ins get a content library built from their Voice-family writing so
  suggestions build on what they've covered. Was a her-specific feature that leaked into the generic
  engine. Her profile already records always-on, so the gate changes nothing for her.

---

## 2026-07-16 — "Base Resume Used" is finally populated; new "Cover Letter?" column

- **The bug, and how long it had been there:** `vet-jobs.js` wrote `Base Resume Used` as an empty
  string with the comment *"filled later by the tailor step"* — but `tailor-jobs.js` never touched
  the rankings files at all. The tailor agent has ALWAYS returned `recommended_base` in its
  `CONFIRM_SCHEMA`; the value was simply discarded on return. So the column was blank in every
  batch ever produced, and the data (which existed all along, inside each per-job
  `application_resume_output*.md`) had to be reconstructed by hand. Jessica had asked about this
  column repeatedly; it read as the system ignoring her, when really it was a handoff that was
  specified in a comment and never built.
- **Fix:** new shared `ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/update_rankings_row.py`. Both
  `tailor-jobs.js` (new `Record` phase → writes `--base`) and `cover-letter.js` (new `Record`
  phase → writes `--cover-letter`) now call it per job. It edits the batch's rankings CSV **and**
  XLSX **in place** — never regenerating — so manual edits, formatting, and local column renames
  survive.
- **Matching is by canonical URL first, job filename second.** Filename alone is not reliable: the
  same posting gets re-fetched under different slugs across batches (Everyday Health exists as
  `...__pm.txt` AND `...__everyday-health.txt`; Google as `google__...` AND
  `product-manager-google-docs__...`), all resolving to one URL via `prep_common.normalize_url`.
  Verified: the writeback lands correctly even when the passed filename is outright wrong.
- **`terse_base()` normalizes the agent's verbose return** into the tracker's house style —
  `'Anthropic — PM, Consumer (6/25/26), copied and renamed to …pages'` → `'Anthropic — PM, Consumer
  (6/25/26)'`; `'(Jan 2026)'` → `'(1/26)'`; `Professional Services` → `Prof. Services`. Matches the
  format Jessica had been hand-entering.
- **New `Cover Letter?` column** (appended last, after `Comp Fit`) answers "which of these already
  have a letter written?" at a glance. New batches get it from `vet-jobs.js`; older 24-column
  batches have it appended automatically on first writeback.
- **A miss is loud, never silent:** if no rankings row matches, the script prints a `WARNING:` line
  naming the key it tried, and the calling agents are explicitly instructed to report it verbatim
  and NOT retry or "fix" it. A silent miss is precisely how the column stayed empty unnoticed for
  so long.
- **Column-count regression check:** `HEADERS` (25) and `dataCells()` (25) verified equal by
  evaluating the real code, not by eyeballing.
- Column renames are tolerated by prefix-matching headers (Jessica's reads
  `"Base Resume Used - Jess-Requested Custom Field"`).

---

## 2026-07-16 — Mission/Scope Fit notes: back to one human sentence, math moved to an optional detail field

- **The problem:** `mission_fit_notes` and `scope_fit_notes` had drifted into dense sub-factor math
  ("Desire = 66 (Mission 11/30 + Role 25/30 + Brand 18/20 + Culture 10/15 + Stage 2/5)...") instead
  of a plain sentence a human can read at a glance. Nothing in the scoring card asked for this —
  it was emergent agent behavior from a "compute it, don't eyeball it" rubric, and the schema's old
  description ("one tight phrase each") was too weak to hold the line against it.
- **Fix (shared engine, `vet-jobs.js` — applies to every ranking run, not just this user's):**
  `mission_fit_notes`/`scope_fit_notes` are now explicitly required to be ONE plain-English
  sentence with no "=", "/", or "+" notation, with a concrete good/bad example pair in the schema
  description itself. Two new OPTIONAL fields, `mission_fit_detail`/`scope_fit_detail`, carry the
  full sub-factor math / hiring-thesis reasoning for anyone auditing a score later — but only the
  Markdown report shows them (indented under the summary line); the CSV/XLSX tracker (what people
  actually scan day to day) never touches the detail fields at all.
- **Not regenerated:** existing rankings (07-16-26, and the archived 07-14-26 project) were left
  as-is — this is a standing-instruction fix for future runs, not a backfill.
- **Also archived** the 07-14-26 historical-rescore project (`build_rescore_workbook.py` + its
  batch folder) to `PRIVATE__YOUR_FILES_GITIGNORED/_ARCHIVED_ONE-OFF_PROJECTS/` — it was a one-off
  built to compare an old vs. new scoring rubric, no longer needed now that there's a single
  resume/scoring source of truth again. This also removes the recurring risk where a formatting
  fix applied to that one-off script's duplicated styling logic didn't propagate to the shared
  `make_rankings_xlsx.py` engine (see the lane-color/alignment fix earlier today) — one less place
  for the same bug to silently reappear in.

## 2026-07-16 — System-level fix: a job can no longer be scored on unverified fetch content

- **The incident:** Microsoft's "Senior Product Manager - AI Skilling" posting failed to fetch
  cleanly — the captured file was ~488KB of the careers site's JS theme config and nav chrome,
  zero actual job text. It was still scored (all four dimensions, final score 44) and shown in
  the rankings as if it were a real read. The user caught it by hand, asking "does Microsoft
  being fully remote change any scores?" — it shouldn't have taken a manual catch.
- **Root cause, found and fixed:** `prep_common.classify()` only ran its "does this look like a
  real job posting" content-marker check when the fetched body was under ~1400 characters. A
  long body full of junk sailed through as `usable` on length alone. Fixed: the content-marker
  check now applies unconditionally, regardless of body length.
- **Hard rule added (Jessica, 7/16/26), three layers deep:**
  1. **Prep now auto-retries with a second fetch method** before quarantining anything.
     `prep_common.process_urls()` takes an optional `fetch_fallback`; `prep_job_urls.py` (the
     primary requests-based fetcher) now automatically spins up Playwright as that fallback
     when installed, and clearly notes in the manifest/report when no fallback was available
     to try (rather than silently only attempting once).
  2. **The scoring agent itself must verify content before scoring** (`vet-jobs.js`): a new
     `content_verified` / `content_issue` pair is required in every per-job schema response,
     with an explicit hard-stop instruction warning that length is not a proxy for real
     content. When `content_verified` is false, the assembler blanks ALL four sub-scores and
     the final score (not just the final one — a lingering sub-score can still look
     legitimate), forces `status` to `"⚠️ NEEDS RE-FETCH — content not verified"`, and sorts
     that row to the very top of the rankings so it can't be missed.
  3. **The spreadsheet flags it loudly** (`make_rankings_xlsx.py`): a row with that status gets
     a jarring magenta fill across the ENTIRE row — not just the Status cell — overriding every
     other per-cell color, since none of a bad row's lane/comp/location data is trustworthy
     either.
- **Retroactively verified** all 12 files in the 07-16-26 batch and all 91 in the 07-14-26
  rescore project against the fixed check — no other silent failures found in either.
- **Also fixed in the same pass** (found while investigating the batch): the Lane column now
  colors by health-domain only (bright green for "Health - Mental Health", lighter green for
  other Health subcategories, no green outside Health — was previously colored by
  lane-priority-match, which is a different question); lane text is now normalized to the exact
  string "Health - Mental Health" (schema + prompt + a deterministic post-processing
  normalizer); a Working-Location parsing bug where "NYC/SF - 3 days" (missing the "IRL"
  prefix) fell through to "Unclear" instead of "Home hybrid"; and `make_rankings_xlsx.py` never
  actually got the left-alignment fix applied earlier this week to the *other* project's
  one-off script — it only ever touched `build_rescore_workbook.py`, never this shared engine
  file, so every ongoing batch kept the old center-aligned columns until now.

## 2026-07-16 — Fixed a syntax bug that silently broke `run-batch` and `vet-jobs`

- **Symptom:** `run-batch` failed immediately with `Error: workflow('vet-jobs'): no workflow with that name`
  — even though `.claude/workflows/vet-jobs.js` existed on disk with the correct `meta.name`. Calling
  `vet-jobs` directly by name also failed as "not found," and only when invoked via `scriptPath` did the
  real error surface: `Script parse error: Unexpected token (64:857)`.
- **Root cause:** an unescaped apostrophe in a schema description string inside `vet-jobs.js` (`"...in
  the candidate's preferred order..."`) closed the single-quoted JS string literal early, breaking the
  whole file's syntax. A workflow file that fails to parse is silently dropped from the runtime's
  workflow registry rather than surfacing a parse error at discovery time — which is why the failure
  first showed up as "no workflow with that name" instead of a syntax error.
- **Fix:** escaped the apostrophe (`candidate\'s`). Verified with `node -c` and by successfully running
  the workflow end-to-end afterward.
- **Context:** discovered while running the 07-16-26 batch (12 URLs pasted into the inbox, 9 fetched
  cleanly — Pinterest and Meta both 403/400'd, Feeld came back too thin at 29 chars, no Playwright
  installed to auto-retry). Vetting, on-ice overlay, and tailoring the top 5 non-on-ice jobs all ran
  successfully against the fixed file.

- **The change.** ChatGPT's second review identified the largest remaining variance source correctly: "is this
  central thesis-defining or merely supporting?" carried enormous weight (only thesis-defining centrals set
  bands) with one sentence of guidance. Added **Step 1c — the Hiring Thesis Test**: four questions (Identity /
  Repetition / Interview gravity / Failure test), decision rule "thesis-defining only when the overall evidence
  strongly supports it; when uncertain, prefer supporting," plus the **core identity ≠ necessary competency**
  distinction. Also **tightened the compounding clause**: two weak thesis-defining centrals compound only when
  genuinely *independent* facets, never when they're one gap named twice. Public template updated in lockstep.
- **One design decision not in the spec: Step 1c runs BEFORE Step 2 grading, and the classification may not be
  revised once grades are visible.** Without that ordering "prefer supporting" becomes a one-way ratchet — a
  scorer seeing `absent` has every incentive to reclassify the requirement as supporting, and the rubric quietly
  stops penalizing anything.
- **⭐ The result that matters: the user's eye was right and the rule change reproduced it.** She called Fetch and
  Peloton "probably in the sixties" by eye, three rubric versions ago. **Fetch 97→70→47→67. Peloton 79→62→44→65.**
  Two agents found it independently, without knowing the target, both identifying that each posting names ONE gap
  from three angles. This is the only external calibration signal the system has ever had, and V2.1 hit it.
- **Canary duplicate control: 1 pt (41/40) — the best ever measured** (V1 = 0 but on a different framing; V2 = 3).
  The V2 residual is closed: it had traced to a duration-qualified central ("3+ years native mobile"), and
  classifying before grading made both agents reproduce the card's own worked example and converge.
- **Net effect ZERO — redistribution, not inflation.** −21 pts across 71 rows (−0.3 mean), yet 19 rows moved ≥8
  pts and chunk nets swung +38/+9/−22/−23 and cancelled. **82+ concentration fell 59% → 54%**, addressing the
  inflation concern without anyone targeting it.
- **⚠️ I predicted this wrong and it's worth recording why.** I forecast V2.1 would push scores UP and worsen the
  concentration, reasoning "prefer supporting → fewer downward band-setters → higher scores." Missed mechanism:
  Step 1c forces scorers to *justify* thesis-defining status, which **promotes centrals as often as it demotes
  them** (Faire −22, Oura −28, Stitch Fix −23 all fell under a rule I expected to be one-directional).
- **⚠️ Methodology bug I introduced: the `v21_delta_note` I asked each agent for is confabulated and unusable.**
  Chunk 4 reported "9 of 14 rows moved upward, typically +12 to +20"; actual movement vs the real V2 run was 3 up,
  7 down, net −22. **Every agent invented a "naive mechanical read" baseline no scorer produced, then credited the
  rule with the difference.** Lesson: a model asked to estimate its own counterfactual fabricates a strawman and
  scores against it. Only a real A/B diff is evidence. Discarded.
- **⚠️ Real bug I introduced: Step 1c broke the `<30` credential band.** Meta's "BA/BS in Computer Science" fails
  all four Hiring Thesis Test questions (not the identity, mentioned once, no interview gravity, an excellent
  candidate succeeds without it) → classified supporting → cannot set the band → Meta should be ~55. But the
  `<30` row names "CS degree *required*" as its own worked example. A scoring agent caught the collision, resolved
  for the credential row (28), and flagged it exactly right. **Credential gates operate at the application, before
  any thesis reasoning exists — a different mechanism, wrongly routed through a capability test.** Fix identified
  (exempt hard credential/history gates from Step 1c); NOT applied — calibration run.
- **The remaining variance moved from classification to GRADING.** Oura (76→48), Stitch Fix (69→46), Faire
  (74→52) each moved ~25 pts with no rule touching them: agents agreed on the band-setter and disagreed on where
  in the band an `absent` thesis-defining central lands. Step 1c tells you *which* central sets the band; nothing
  tells you *where in the band*. Largest measured disagreement now.
- **Pressure point for the freeze decision:** Everyday Health's SEO ask passes 3 of 4 tests and fails Repetition
  outright (one bullet, absent from responsibilities). Thesis-defining → 42; supporting → ~85. **43-pt swing on
  one call**, and the decision rule points both ways. The test concentrated variance from many small judgments
  into one big explicit one — progress, but it needs a tie-breaker.
- Both workbooks rebuilt. Full report: `1 - Rankings/V2.1-calibration-report.md`. V2.1 is a candidate baseline
  pending review — not adopted.

---

## 2026-07-15 (later) — Formatting fixes in workbook builder + lane taxonomy corrected

- **Lane formatting: hyphens instead of middle dots.** The lane taxonomy was outputting "Health · Mental
  Health" instead of the spec'd "Health - Mental Health". Fixed the payload data (all 71 rows) and
  rebuilt both workbooks with the corrected format. Going forward, lane fields will use hyphens.
- **Column alignment: text columns left-aligned.** The main ranking workbook was centering all columns.
  Fixed `build_rescore_workbook.py` to left-align Lane, Company, Job Post Title + Link, and Working
  Location (columns 3–6), while keeping scores and other data centered. Both workbooks rebuilt.
- **Root cause:** Lane mapping was using middle dots as hierarchy separators; the workbook builder had
  no awareness of text vs. numeric columns. Fixes applied directly to payload and the builder script.

---

## 2026-07-15 (calibration run) — V2 rescored all 71 blind; duplicate control passed at 3 pts; top-band concentration got worse, not better

- **The run.** 5 blind agents, 14–15 jobs each, reading only the revised card §2 and profile PART 1. V1
  scores snapshotted first and never shown to any scorer; agents instructed not to anchor and not to
  shape the distribution. Full report: `1 - Rankings/V2-calibration-report.md`.
- **Canary duplicate control PASSED at 3 pts** (rows 3/51, MD5-verified identical, different chunks,
  different agents): 36 vs 33 on Profile Fit, 55 vs 52 on the final. Both agents landed the same band,
  the same band-setter, and the same coherence call — the reasoning converged completely.
- **The residual 3 pts found a real rule gap, which is the run's most useful output.** It traces to one
  grade call on identical Kngroo evidence (`direct (thin)` vs `light`) against a central carrying a
  **duration qualifier** ("3+ years native mobile"). The 7/15 fix says grade `direct` from evidence
  alone without requiring recurrence — but is silent on evidence measured against a requirement that
  *itself* demands sustained duration. Both readings are defensible under the current text. **Highest-
  value fix available; not applied (calibration run, no architectural changes).**
- **The fix-#1 evidence/coherence split is demonstrably working**, produced independently by three
  agents. Best proof: **Paperless Post 97 vs Fetch 47 — same underlying evidence (her invite-loop
  work), scored by the same agent in the same chunk, credited at one and refused at the other**, with
  the distinction stated in a line (invitation *sending* is what she owned; a rewards/incentive engine
  is not). Two agents stated the counterfactual arithmetic unprompted — Faire: *"grading the evidence
  and the coherence separately is what puts this at 74 rather than either ~88 (evidence-only) or ~50
  (coherence folded into the grade)"*; Alloy: *"a pre-split reading would have graded this materially
  lower."*
- **The Step 3 guardrail (fix #4) drove most of the large increases** by correctly demoting domain and
  spike requirements to company *context* or explicit bonuses: Talkspace 65→87 (mental health is
  context; the thesis is onboarding/activation), Prava 66→87 (posting labels healthcare "Bonus" →
  Rule B forbids gating), Figma 79→92 (every design-tools spike is explicitly "not required"), Stitch
  Fix 34→69, Oura 46→76. V1 had been letting bonus items and context do centrals' jobs.
- **⚠️ Honest negative result: the 82+ concentration ROSE from 52% to 59%.** ChatGPT's "is the scale
  still inflated" concern is now more pronounced, not less. Two readings, and this run cannot decide
  between them: (a) the bands changed meaning — V1's 82–96 claimed "comfortably shortlisted" (a pool
  claim), V2's claims "the career tells this story convincingly" (narrative only, a weaker and more
  defensible assertion), and these are jobs she self-selected as career-matching; or (b) residual
  leniency the rewrite didn't fix. **What did clearly improve: separation** — stdev 17.5→18.8, the
  68–81 middle hollowed out (12→7) while the tails filled (30–49: 7→9). Resolving (a) vs (b) needs
  real application outcomes, not another rubric pass.
- **⚠️ Flagged for the user, not silently accepted: Fetch (47) and Peloton (44) are now materially
  BELOW her stated intuition** ("probably in the sixties" for both). Trajectories: Fetch 97→70→47,
  Peloton 79→62→44. Suspected cause: the guardrail's **compounding clause** may over-penalize when two
  weak centrals are two facets of the *same* specialization rather than independent gaps. Candidate fix
  identified, not applied pending her judgment.
- **Five pressure points documented, no rubric changes made** (per the run's terms): duration-qualified
  centrals (above); postings that file one capability as both requirement and bonus (Adobe); whether
  narrative softeners can move a band or only position (Headway); **no mechanical test exists for
  "thesis-defining vs supporting"** — now the highest-leverage judgment in the dimension and worth ~18
  pts on a single posting alone, with one sentence of guidance; and Alignerr (Profile Fit 97 / Desire 18)
  as the known "top of a weak pool" blind spot — behaving *correctly*, flagged so it doesn't get
  "fixed."
- Both workbooks rebuilt. V2 is a candidate baseline pending review — not yet adopted.

---

## 2026-07-15 (even later) — Four logic bugs fixed in the hiring-thesis rewrite before the rescore ran

- **A second round of ChatGPT review, this time on the hiring-thesis rewrite itself, caught four real
  bugs before any of the 71 jobs were rescored under it.** All four accepted and fixed in
  `01-scoring-card.md` §2:
  1. **`direct` was defined too narrowly.** It required the evidence to *also* connect to a career
     throughline, conflating "did she do this" with "does her career repeat this pattern." That would
     force real direct experience (e.g. Kngroo's native-iOS ownership) down to `transferable` just
     because mobile isn't a throughline. Split into two separate judgments: `direct` is graded from
     the evidence alone; a new **narrative-coherence** step (after Step 2) handles repetition
     separately — it can move her position within a band, or cap the band's ceiling on a role whose
     thesis explicitly requires sustained specialization, but it never changes whether one example is
     `direct`.
  2. **The candidate profile contradicted itself about what counts as a gap.** "Only these six items
     are gaps" directly conflicted with the card's own instruction to grade an unlisted, clearly-
     required specialization `candidate-silent` → `absent`. Renamed the section **Confirmed Recurring
     Gaps and Boundaries** and rewrote its rule: the list covers gaps confirmed during intake and
     likely to recur across many roles — it is explicitly NOT exhaustive, and a per-job `absent`
     finding on an unlisted specialization is a job-scoped evidence judgment, not a new permanent
     claim, and must not be added to the list or reused on a different job with a different thesis.
     Same fix applied to the public template so future users don't inherit the contradiction.
  3. **Rule B smuggled the fabricated applicant pool back in.** "Covering 0-of-N is direct evidence
     that better-matching careers exist" is an inference about hypothetical other candidates — exactly
     what the rewrite was supposed to remove. Reworded: the deduction is earned by her own profile's
     incompleteness against the posting's stated ideal, not by a claim about who else applied.
  4. **"The weakest central sets the band" had no guardrail against a secondary item dominating.** Added:
     before a central can set the band, it must be verified as **thesis-defining** (part of the Step 0
     identity), not merely a supporting requirement that happens to pass the Centrality Test. A weak
     supporting requirement moves her position within a band; only a weak thesis-defining central can
     force a lower band. Tightened the sanity check to require naming *why* the gap undermines the
     hiring story, not just that it appeared in the requirements section — this is what stops Cloaked's
     secondary "read code when useful" ask from overpowering its explicit retention/engagement thesis.
- **Two smaller, accepted profile refinements** in `02-candidate-profile.md`: throughline #2 renamed
  "Onboarding, activation, and helping people become more capable," with a line naming that it shows up
  in hiring/mentoring/career development/community-building/Ascend, not just product activation —
  the prior wording underplayed the human-development thread relative to what's actually documented.
  Throughline #6 (community/founder ecosystems) changed from "never the headline" to "supporting in
  most roles; potentially central when the hiring thesis itself concerns smaller organizations,
  community-led growth, founder enablement, or nonprofit capacity-building" — closer to the evidence
  without licensing every incidental "community" mention to inflate a score.
- **What was reviewed and rejected:** nothing — all four scoring-card fixes and both profile
  refinements were assessed as correcting real logic errors (verified against the actual file text
  before editing, not taken on faith) and applied as proposed. No open-ended rewrite beyond these six
  changes, per the reviewer's own recommendation not to risk bloating a structure that's otherwise
  sound.
- The 71-job rescore still has not run. This was a second, necessary correction pass before it does.

---

## 2026-07-15 (later) — Profile Fit rewritten around "hiring thesis + narrative coherence"; pool-ranking retired same day it shipped; candidate profile becomes a reasoning document

- **Where this came from.** The user took the scoring system to ChatGPT for an independent second
  opinion and came back with an architectural revision, which survived review here with guards
  added. Core critique accepted: the pool-ranking frame (shipped earlier today) had the scorer
  estimating percentile rank in an applicant pool it has never seen — confident-sounding
  fabrication. The dimension (formerly "Market Perception," now **"Profile Fit — how they see
  her"**; CSV field and spreadsheet column names unchanged) now asks: **how strongly would this
  company perceive the documented career as matching the person they're trying to hire, from
  application through interviews?**
- **The conceptual shift: narrative coherence over requirement checklists.** Scoring starts by
  stating the role's **hiring thesis** (ledger row zero — what kind of person is this company
  actually trying to hire, the identity behind the title). Rule A recast from "the specialization
  the role is NAMED for" to "the hiring thesis is always central" — the title is evidence of the
  thesis, not the thesis. Repeated career themes (throughlines) earn narrative credit; one isolated
  analogous bullet does not. New **interview test**: a grade must survive "tell us about the X
  you've built." New mandatory **misclassification check** against the profile's new Common
  Misclassifications list (invitations ≠ referral programs, notification system ≠ ESP execution,
  AI builder ≠ production AI shipper, …).
- **`unknown` split in two; the 68 floor deleted.** `posting-ambiguous` (vague posting) = neutral,
  cannot set the band. `candidate-silent` (posting clearly asks; profile has no named evidence) =
  runs the name-the-evidence test honestly, usually `light`/`absent`, plus a logged question for
  the user. The old single `unknown` with its "may never set a band below 68" floor manufactured
  optimism exactly where a recruiter would see a hole.
- **Kept, deliberately, against the grain of the rewrite:** the whole mechanical skeleton — ledger,
  Centrality Test with hard cap 6, evidence-grade definitions, name-the-evidence test, one-concern-
  one-deduction, Rule B (bonuses rank, never gate; no bonus section = neutral), Rule C (no upward
  tie-break, now phrased via the interview test). Reason: this session repeatedly measured that
  holistic judgment does not reproduce (29-pt spread on the byte-identical Canary control) and
  mechanical structure does (spread 0). "Narrative coherence" is *more* holistic, not less; the
  skeleton is what keeps it honest. **The Canary duplicate-row control remains the acceptance test
  for the upcoming rescore: >~3 pts of spread on Profile Fit = the wording failed, iterate before
  accepting any numbers.**
- **`02-candidate-profile.md` restructured from biography to reasoning document:** Career Identity →
  Career Throughlines → Clearly Established Strengths → **Adjacent Experience** (real experience
  that is NOT a defining specialization: mobile, growth, healthcare, production AI, enterprise,
  marketplaces, SMB) → Genuine Gaps → **Common Misclassifications** → seniority/education → compact
  Career History. The PART 1 evidence / PART 2 preferences wall survives untouched. Throughlines
  were verified against the experience-bank/positioning canon before inclusion (community/founder-
  ecosystem work is documented there; "nonprofits" was in the user's ChatGPT discussion but has no
  documented evidence, so it was left out).
- **Public templates updated in lockstep** (`02-candidate-profile.template.md` restructured to the
  reasoning-document shape; `01-scoring-card.template.md` §2 + Fit fair-scoring rules rewritten to
  hiring-thesis/narrative framing, two-kinds-of-silence, bonus-rank rule) so a future `/intake`
  run generates the new structure for any user. Templates stay generic.
- Full 71-job rescore under the new rubric is pending the user's review of the two rewritten
  private files (deliberate hard stop — a wrong self-description in the profile would poison all
  71 scores).

- **The problem the user named.** Reviewing the rescored batch, she didn't trust Market at all:
  Fetch 97 despite the posting explicitly wanting someone who'd built referral programs, Cloaked 98
  despite an explicit "can read real code" ask, Peloton 79 despite 0-of-5 bonus items. Her framing
  is the fix: a recruiter isn't checking whether she clears a bar, they're stacking her against the
  other resumes in the pile. **Market now asks "where does she rank in the applicant pool," not
  "does she satisfy the requirements."** Both band tables reworded accordingly: 97-100 top handful /
  82-96 comfortably shortlisted / 68-81 gets a look but better-matched candidates exist / 50-67 needs
  a referral / 30-49 likely screened out / <30 credential gate.

- **Three rules added, because the reframe alone wasn't reproducible.**
  - **Rule A — a named specialization in the title or spine is always central, and it cuts both
    ways.** It's what most rescored the batch. Up: Paperless Post 95 (its "Send and Manage" spine
    *is* the notification system she owned), Cloaked 95, Clio 92. Down: EllieMD 42 (a hardware
    spine she has nothing for), Stitch Fix 34, Fetch 70, Hims & Hers 80.
  - **Rule B — bonus/preferred sections rank but never gate; no bonus section = neutral.** Prevents
    a posting that simply doesn't list nice-to-haves from being scored as though she failed them.
  - **Rule C — no upward tie-break.** Deliberately deleted the tie-break added earlier the same day.
    Worth being precise about why, since it looks like a reversal: "omission ≠ absence" and
    "imperfect ≠ implausible" govern how you read *her profile* and still stand. Rule C governs how
    you rank her against *other applicants* — and against a real pool, ties don't break her way.

- **The evidence, captured because the trial predicted it.** Fetch 97→70, Cloaked 98→95, Peloton
  79→62 — all three landed where the user said they should sit by eye.

- **The Canary control (rows 3 and 51: same URL, byte-identical files, scored blind by two agents)
  held at spread 0 on Market — 42 vs 42.** Both agents independently graded the SDK requirement
  `absent`; the upward tie-break had been the only thing holding it at `light`/62. The framing change
  moved the control 20 points *in unison*, which is what a genuine rule change should look like as
  opposed to noise. Full-score spread on the control is 2 points (57 vs 55).

- **Methodology note worth keeping: chunk-mean spread is not a variance measure.** Mid-run I nearly
  reported an "18.9-point agent-to-agent spread" as a calibration failure. It was composition, not
  bias — the chunks hold different jobs, and the high chunk contained Asana (literally her former
  product) while the low chunk held Meta, Stitch Fix, and Canary. Only the duplicate-row control
  compares two agents on identical input. **Don't infer scorer disagreement from statistics over
  non-identical samples.** Related earlier lesson, same failure family: I prematurely declared the
  ceiling model broken on 4 of 5 chunks when the missing chunk held the decisive control.

- **Known blind spot, not fixed.** Market rewards "top of a weak pool" identically to "top of a
  strong pool" — Alignerr scores Market ~98 with a Desire of 18. A high Market is a statement about
  her odds, not about whether the job is worth wanting. The weighted final (Desire 35%) is what
  absorbs this, but the Market column read alone will mislead.

- Batch result across 71 rows: Market 27-98 (mean 76.6, was 82.7 under the ceiling model);
  final 46-91 (mean 73.1). The 50-75 middle no longer clusters.

---

## 2026-07-14 (evening) — De-anchor fix was incomplete; comp-band coloring semantics questioned

- **The earlier same-day de-anchor fix missed 5 rows.** The list of "companies named in the scoring
  card" was built from memory of the anchor tables rather than by systematically extracting every
  proper noun from the file, so the keyword search omitted `playlist`, `google`, `asana`, and
  `justworks`. The fix was reported as covering "10 affected rows"; it should have been 15. Caught
  only because the user flagged that Mindbody's Desire (32) and Market (55) were obviously wrong.
  **Lesson: when auditing "everything matching a pattern," extract the pattern set from the source
  file programmatically — never enumerate it from memory, and never report a count that came from a
  hand-built list.**
- Rescoring the 5 (Playlist ×2, Google, Asana, Justworks) produced the strongest evidence yet that
  the de-anchor fix is correct: the two Playlist rows — same company, same brand — now sit **30
  Desire points apart** (Founding AI PM 88 vs. Professional-Services Lead PM 58), because the rubric
  now scores the role rather than the logo. Mindbody's Market went 55 → 78 once the card's own
  Profile-Fit protections (count one gap once; "plus"/"ideally" is not a day-one gate) were actually
  applied.
- **Open engine question — comp band semantics.** `make_rankings_xlsx.py` already color-codes the
  Comp Range column for all users (good), but `compFitLabel()` in `.claude/workflows/vet-jobs.js`
  classifies the band using `max(range)`, so a posting of `151-201` against a 180 floor / 200 target
  paints **green ("meets/above target")** even though the midpoint (~176) is below the floor — a
  green cell directly contradicting a "below floor" note. The one-off rescore workbook now uses a
  stricter midpoint rule (green only if midpoint ≥ target; red only if max < floor; yellow for
  straddles). Not changed in the shared engine because it affects every user — needs a decision.

## 2026-07-14 (later still) — Location color/score derived from the posting instead of the authoritative spreadsheet (batch bug + general lesson)

- The user spotted a row (Prava Therapy) whose Working Location cell said "Remote" but was
  colored red with a Comp+Lifestyle score of 22. Root cause in the one-off
  `build_rescore_workbook.py` / rescore flow: the scoring agent decided `location_tier` (the
  cell color) and the location component of practicality from its own read of the **job
  posting**, instead of from the candidate's **authoritative spreadsheet** Working Location —
  violating the historical-rescore source-of-truth rule ("spreadsheet wins for location, never
  overwrite it"). It failed both ways: remote/home-metro rows shown as penalized (Prava,
  Everyday Health, Thoughtly), and in-office NYC rows shown as green/remote (Biograph, Playlist,
  Forus, Faire, Gaia Family).
- Fix (batch outputs only, not shared engine): `location_tier` is now derived deterministically
  from the sheet's Working Location text by one rule (Remote→green; NYC 1–2 days→yellow; NYC
  3+/unclear/multi-hub→orange; non-NYC required→red) for all 71 rows — 17 colors corrected.
  Practicality re-scored for the 3 rows whose location itself was mis-scored (Prava 22→78,
  Everyday Health 15→48, Thoughtly 35→68). Detail in that batch's `1 - Rankings/QA-report.md`
  (draft 6).
- **General lesson for the engine:** a color/tier classification like this should be computed
  deterministically from the normalized location string, never decided by the LLM — the LLM
  conflated "great fit for her (NYC home base)" with "remote-first (green)". The real engine
  already does this correctly (`make_rankings_xlsx.py` maps deterministic `locationFitLabel`
  output → color); the bug was only in the one-off rescore workbook builder, which had let the
  LLM choose the tier. Worth guarding against if `location_tier`-style LLM fields are ever added
  to the shared path.

## 2026-07-14 (later) — Named-company scoring-card anchors found outside Market Perception and fixed; resolves the original Knit mystery

- While rescoring Spring Health against real posting text supplied by the user, found that
  `PRIVATE__YOUR_FILES_GITIGNORED/03-VETTING__YOUR_PRIVATE_INFO/01-scoring-card.md` still named
  specific companies directly as scoring anchors in the **Desire tier table, Company Style anchor
  table, and Practicality anchor table** (e.g. "Company Style 45–61 = Spring Health," "Desire Tier 3
  = Knit," "Practicality 96 = Skylight"). The earlier same-day migration audit had fixed this exact
  bias pattern in the Market Perception table only — this is the identical failure mode (a score
  reproducing because the rubric names the company in that band, not because of the posting's actual
  content), just missed in three other tables.
- All named-company language was scrubbed and replaced with abstract evidence patterns, matching the
  style already used for Market Perception. 10 already-scored rows in the in-flight historical
  rescore batch had their company named in one of these tables (Spring Health, Oura, Headway,
  ClickUp, Kindred, LTK, Knit, Meta/Instagram, BetterUp, Peloton) and were rescored fresh against the
  fixed rubric.
- **This resolves the original mystery that started the whole migration audit**: Knit's score moved
  from 53 to 74 (+21) purely from removing its own named anchor — strong evidence the original
  58→38 drop was a real, structural scoring-card bug affecting every named company in these tables,
  not something specific to Knit. Full before/after detail in
  `__READY_TO_REVIEW__PRIVATE_GITIGNORED/07-14-26 RESCORE ALL THE JOBS!/1 - Rankings/QA-report.md`.
- Separately, two of the historical rescore's 5 "posting taken down" reverts (Spring Health, Hone
  Health) turned out to be wrong: the user supplied the actual saved posting text directly, proving
  the automated fetcher was blocked, not that the jobs were gone. Take "fetch returns nothing" as
  "couldn't retrieve," not "doesn't exist," when a user-supplied copy is available to check against.
- Same pattern closed out the last 3 gaps: the user supplied real posting text for Clio (fetch had
  genuinely 403'd), Skylight (fetch hit a JS-rendered page and got nothing, no Playwright available),
  and Adobe/Design at Adobe (fetch actually succeeded both times but landed on a real "this job has
  been filled" notice — a genuine closed-posting signal, unlike the Spring Health/Hone Health false
  alarms). All 71 rows in the historical rescore batch now have live, verified scores; zero remain
  reverted to a historical/unavailable placeholder.

## 2026-07-14 — Migration audit fixes shipped; historical rescore test found and fixed a serious fuzzy-matching bug

- Root cause of the Knit job's old-vs-new score drop (58→38 on Market Perception) was
  audited rather than assumed: found the candidate profile file had drifted/thinned
  during the deprecated Job Pipeline → JAIL migration, the scoring card had named-company
  anchors and a duplicate/contradictory band-cutoff table, and lane taxonomy had gone
  free-form. Fixed all three: rebuilt `PRIVATE__YOUR_FILES_GITIGNORED/
  03-VETTING__YOUR_PRIVATE_INFO/02-candidate-profile.md` (evidence vs. preference
  sections split, restored dropped details like 0→1/founder history, hands-on AI
  building reframed as strength not gap), consolidated the scoring card to one band
  table with general fair-scoring protections (day-one-gate-vs-learnable, count-gap-once,
  omission≠absence), and constrained Lane to a `<Bucket> - <Subcategory>` pattern in
  `.claude/workflows/vet-jobs.js`. Equivalent general (non-personal) guidance was mirrored
  into the public `.template.md` files and `.claude/skills/intake/SKILL.md` so future
  users get the same protections without any Jessica-specific data leaking into templates.
- Workbook column layout became dynamic instead of hardcoded: `make_rankings_xlsx.py`
  now reads a per-run `<batch>-rankings.meta.json` (written by `vet-jobs.js`) for score
  labels/weights, and the 24-column layout was reordered to an exact requested order
  (contiguous score block, `Base Resume Used` added, deprecated `ClaudeStatus`/lane-dupe
  columns dropped). `resolve_submitted_applications_link()` was simplified from
  directory-scanning to reading one explicit `archive.current_year_path` config value.
- Location handling fixed: NYC/SF abbreviated everywhere (general); Jessica's multi-city
  postings now order by an explicit `location.city_priority` list in `jail.config.json`;
  a bug where `"IRL NYC - unknown days"` was mis-resolving to `"Unclear"` (the
  unknown-substring check ran before the IRL/onsite check) was fixed. Added a Lever
  fetcher and a generic schema.org `JobPosting` JSON-LD fallback to `ats_fetchers.py` for
  non-ATS sites, used by both the sync and Playwright prep scripts. Added a first-run
  completeness nudge so a new user's first vetting pass warns if `jail.config.json` is
  missing comp/location/lane info instead of silently scoring against gaps.
- **Historical rescore test** (71 real historical job rows, run as a one-off validation
  against the fixed engine): surfaced a serious bug in my own local-file-matching logic,
  not the engine. A fuzzy company+title matching fallback (used when no exact filename/
  URL match existed) was checked at low confidence scores first, found wrong, and on
  digging further **all 33 fuzzy matches at every confidence level (2 through 5) turned
  out to be wrong** — including the batch's single highest-scoring row. Every match was
  re-verified by comparing the candidate file's own `URL:` header against the row's real
  hyperlink (the only reliable method found); 28 of 33 were corrected via real re-fetch,
  5 were genuinely unavailable (postings taken down or bot-blocked/JS-rendered) and
  reverted to their original historical scores rather than guessed at. Full account,
  including a related "plausible placeholder score" schema loophole (an agent returning
  a fake-but-in-range 50/50 instead of an honest 0 when a file couldn't be read) and a
  large-JSON read/write truncation failure mode in the Workflow harness (fixed by
  chunking), is in `__READY_TO_REVIEW__PRIVATE_GITIGNORED/07-14-26 RESCORE ALL THE JOBS!/
  0 - Prep Report/prep-report.md` and that batch's `1 - Rankings/QA-report.md`.
  Conclusion for future engine work: never ship a fuzzy-match fallback without a
  mandatory content/URL verification step — score-level plausibility alone gave no real
  signal of match quality.

## 2026-07-13 — Changelog capture became mandatory, synthesis lost its API dependency

- `CLAUDE.md` now requires every coding agent — Claude Code, Codex, or otherwise — to
  add a rough `docs/changelog.md` entry in the same turn as any meaningful change, or
  state why none is needed. This was previously only a soft pointer, not a completion
  requirement, and rough entries were not being captured automatically as a result.
- Added `AGENTS.md` so Codex finds the same rule without a duplicated copy.
- Removed the direct Anthropic API call from `scripts/doc_synthesis.py`. The original
  design assumed unattended, standalone synthesis (mirroring an external reference
  implementation), but the actual workflow asks an active Claude Code or Codex session
  to perform synthesis itself. The script now only gathers Git evidence and manages
  the deterministic structure/marker; no API key is needed anywhere in this repo.
- The private Writing home this repo symlinks canon from was reorganized (see its own
  git history) — three symlinks under `PRIVATE__YOUR_FILES_GITIGNORED/
  04-TAILOR__YOUR_PRIVATE_INFO/` were repointed to match: the two Ascend canon files
  and `cover-letter/writing-links.md`. Verified with a real lint run through the
  updated symlink chain — resolved and read cleanly, no path errors. The other 12
  symlinks in that folder were unaffected (their targets didn't move).

## Pre-2026-07-13 — Everything before the changelog existed

- JAIL shipped its V2 pipeline (Prep → Vet → Tailor → Reconcile/Archive) and the
  three-root layout (`ENGINE__PUBLIC_GIT_TRACKED` / `PRIVATE__YOUR_FILES_GITIGNORED` /
  `__READY_TO_REVIEW__PRIVATE_GITIGNORED`) before this changelog began. See
  `docs/v2-end-to-end-workflow.md` and `docs/testing-and-caveats.md` for that history.

## Earlier — Origins

- The project began as a single-purpose resume tailoring helper and grew into the full
  chained pipeline described in `README.md`.
