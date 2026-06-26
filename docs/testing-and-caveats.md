# Testing & caveats (builder / operator notes)

The honest, builder-facing record of what's verified and what still needs a live run. Beginners don't need this — the README's "review your outputs" note is enough. This is the detail.

## What passed offline

V2 was built and tested **without** a live Python environment, so the pure logic was validated with offline fixtures + structural checks (each unit committed only after its checks passed; see `v2-end-to-end-workflow.md` → Implementation status, and the `v2-unit-*` git commits):

- **Unit 4 — prep reliability:** URL normalization/dedupe, thin/failed classification, collision-safe filenames, quarantine placement, the manifest + report, and manifest-aware retry all passed an offline fixture test (a synthetic mix of duplicate, normalized-duplicate, thin, failed, and usable URLs through a stubbed fetcher).
- **Unit 5 — candidate-relative ranking:** the comp-fit, location-fit, config-loading, and missing-config logic in the colorizer passed pure unit tests (no `openpyxl` needed); `vet-jobs.js`'s `lane_fit` schema + config inlining were verified structurally.
- **Unit 6 — archive + reconcile:** the `/archive` move algorithm (move-not-copy, collision suffix, final-PDF heuristic, config fallback, workspace-leftover detection) passed a shell simulation mirroring the skill; `reconcile.js`'s config-aware path, year-subfolder scan, `05a`/`06a` appends, and the primary-file gate were verified structurally.

## Passed on synthetic / local demo data (V2.1 — 2026-06-25)

The synthetic demo kit (`docs/examples/jordan-lee-demo/`, persona "Jordan Lee — AI Product Marketing / GTM") was run end-to-end on local, gitignored synthetic data (batch `06-25-26`). With the venv in place (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`; `openpyxl 3.1.5`), these previously-untested paths were exercised for real and **passed on synthetic data**:

- **Ranking spreadsheet render (Unit 5)** ✅ — the real `vet-jobs` workflow scored 4 synthetic posts and `03-VETTING/make_rankings_xlsx.py` rendered the `.xlsx` via `openpyxl`. Confirmed: the candidate-relative fit columns + colors (comp vs target/floor, location vs the candidate's per-arrangement ratings), the status-aligned final score, and the quarantine note all render correctly. Committed artifact: `docs/examples/jordan-lee-demo/expected-outputs/rankings.xlsx`. *(The column layout was reworked in **V2.2** — see the V2.2 note below.)*
- **`/archive` (Unit 6)** ✅ — archived a synthetic submitted folder: move-not-copy (source removed), config-aware path + `2026` year subfolder, readiness check, and `archive-summary.md` all behaved as specified.
- **`/reconcile` (Unit 6)** ✅ — reconciled the synthetic archived folder: the config-aware no-args scan resolved `archive.path` from `jail.config.json`, read the final PDF as ground truth, wrote the per-folder reconcile report, and created the ledger / queue / `05a` / `06a` learning instances from their templates. (The PDF was read via the Read tool; a `.pages`/`.docx`-only folder would still need an exported PDF.)

> **Important — what this run did NOT test.** The **prep report + manifest in that run were hand-curated / hand-placed to match the real `02-PREP/prep_common.py` output format — they were NOT produced by a live fetch.** No network request was made. So the live job-post fetch (below) remains genuinely unverified; do not read "the synthetic demo passed" as "fetch works."

## Passed on synthetic data (V2.2 — Tracker UX — 2026-06-26)

The rankings output was reworked into a job-search **tracker** (see `v2-end-to-end-workflow.md`). The synthetic demo artifacts were **regenerated** and verified:

- **Tracker render** ✅ — `make_rankings_xlsx.py` builds the 23-column human-first layout and re-loads cleanly via `openpyxl`. Confirmed in the rebuilt `rankings.xlsx`: header **frozen** (`A2`), all cells **wrapped/centered/top**, an inline **Status dropdown** (`showDropDown=False`, the 12 values) on the job rows only, **auto-filter** `A1:W5`, lifecycle **Status** colors, **Lane** stoplight (p1 green / p2 amber / Outside red), candidate-relative **Location/Comp Fit** colors, the score ramps, an **Instructions** tab, and a **separate section-color legend** (merged `A:J` bars below the jobs, vivid palette). The **job rows contain no merged cells, so they sort cleanly** (matches the user's working reference workbook). No `Category` / `ClaudeStatus` columns.
- **Lane vs Lane Fit fix** ✅ — the Lyceum row renders `Lane = "Product Strategy / AI Research"` (red — outside) with `Lane Fit = "Outside lanes (high)"`; the old contradiction (a forced `Category = "AI Product Marketing"`) is gone.
- **Fit-math single source** ✅ — the comp/location label functions ported to `vet-jobs.js` produce labels **identical** to the former Python implementation across all four synthetic rows (checked directly); `make_rankings_xlsx.py` now only maps labels → colors.
- **Status reconciliation** ✅ — `vet-jobs` `statusFor` emits only dropdown values (`Skip` → `Apply Eventually: Or Skip It`); `run-batch`'s tailor-filter updated to match. Both workflow files pass a Node syntax check.

> Not re-run live: the full `vet-jobs` workflow was not re-executed against the staged batch (the committed artifacts were regenerated deterministically to preserve the curated scores). The scoring/CSV-writing JS was syntax-checked and its fit functions unit-checked; an end-to-end live re-run remains optional.

## Still remaining / not yet tested

- **Live job-post fetch (Unit 4)** — the only network-bound path, still **unverified against reality**. Needs `requests` / `trafilatura` / `bs4` (+ optional `playwright` for the renderer). Run it as a **separate, disposable real-URL smoke test**: scaffold a throwaway batch, paste 3–5 real public job URLs, run `02-PREP/prep_job_urls.py`, and confirm the prep report + quarantine behave on real pages. Local only — **never committed, never screenshotted**; record a dated pass/fail note here if useful. (V2.1 Unit 6.)
- **Real-URL prep across live ATS pages** — Greenhouse / Lever / Ashby / Workday / LinkedIn-guest parsing, URL dedupe, and thin/failed classification on actual postings. Part of the same real-URL smoke; not yet run.
- **Screenshot capture** — the synthetic runtime is staged and the `expected-outputs/` artifacts exist, but the PNGs under `docs/screenshots/` have not been captured yet. (V2.1 Unit 5.)
- **GitHub Mermaid render** — the README + `v2-end-to-end-workflow.md` Mermaid diagrams have not been confirmed to render on GitHub.
- **Website handoff** — `docs/jail-public-page-copy.md` is suggested copy only; the external site (a separate repo) has not been updated.

None of these block the offline build or the synthetic demo — they're the "confirm it against reality / publish" pass.

## Note for users
This is an early, local workflow. **Review its outputs before relying on them** — the rankings, the tailored drafts, and especially anything it flags as a guess. It's built to make the work faster and more honest, not to be trusted blindly.
