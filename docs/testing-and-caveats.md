# Testing & caveats (builder / operator notes)

The honest, builder-facing record of what's verified and what still needs a live run. Beginners don't need this — the README's "review your outputs" note is enough. This is the detail.

## What passed offline

V2 was built and tested **without** a live Python environment, so the pure logic was validated with offline fixtures + structural checks (each unit committed only after its checks passed; see `v2-end-to-end-workflow.md` → Implementation status, and the `v2-unit-*` git commits):

- **Unit 4 — prep reliability:** URL normalization/dedupe, thin/failed classification, collision-safe filenames, quarantine placement, the manifest + report, and manifest-aware retry all passed an offline fixture test (a synthetic mix of duplicate, normalized-duplicate, thin, failed, and usable URLs through a stubbed fetcher).
- **Unit 5 — candidate-relative ranking:** the comp-fit, location-fit, config-loading, and missing-config logic in the colorizer passed pure unit tests (no `openpyxl` needed); `vet-jobs.js`'s `lane_fit` schema + config inlining were verified structurally.
- **Unit 6 — archive + reconcile:** the `/archive` move algorithm (move-not-copy, collision suffix, final-PDF heuristic, config fallback, workspace-leftover detection) passed a shell simulation mirroring the skill; `reconcile.js`'s config-aware path, year-subfolder scan, `05a`/`06a` appends, and the primary-file gate were verified structurally.

## Remaining live-test caveats (need the Python venv)

These pass their offline/structural tests but haven't been exercised end-to-end against the real environment. Set up the venv first — `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` — then:

1. **Live job-post fetch (Unit 4)** — needs `requests` / `trafilatura` / `bs4` (+ `playwright` for the renderer). Scaffold a batch, paste a few real job URLs, run `02-PREP/prep_job_urls.py`, and confirm the prep report + quarantine behave on real pages.
2. **Live ranking spreadsheet render (Unit 5)** — needs `openpyxl`. Run a real vet pass (or feed a fixture CSV + `jail.config.json`) through `03-VETTING/make_rankings_xlsx.py`, open the `.xlsx`, and confirm the Comp Fit / Location Fit / Lane Fit columns, candidate-relative colors, and the A1 note render.
3. **Live `/archive` (Unit 6)** — archive a synthetic submitted folder and confirm move-not-copy, the year subfolder, and `archive-summary.md`.
4. **Live `/reconcile` (Unit 6)** — needs the pdf skill to read the final PDF. Reconcile a synthetic archived folder and confirm the report + ledger/queue/`05a`/`06a` writes.

None of these block the offline build — they're the "confirm it works against reality" pass.

## How V2.1 exercises these (synthetic-first)

The synthetic demo kit (`examples/jordan-lee-demo/`, persona "Jordan Lee — AI Product Marketing / GTM") doubles as a synthetic test bed. Stage its fixtures into the real (gitignored) runtime folders and run the local-deterministic caveats against synthetic data: the **xlsx render**, **/archive**, and **/reconcile** all run without network or real materials, and they also produce the committed demo artifacts.

The **live job-post fetch** is the only network-bound caveat. Exercise it as a **separate, disposable real-URL smoke test**: 3–5 real public URLs, local only, **never committed and never screenshotted** — record only a dated pass / fail note here if useful. Real-URL results never feed public demo screenshots.

## Note for users
This is an early, local workflow. **Review its outputs before relying on them** — the rankings, the tailored drafts, and especially anything it flags as a guess. It's built to make the work faster and more honest, not to be trusted blindly.
