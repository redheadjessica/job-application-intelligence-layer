# docs/screenshots/

Committed screenshot PNGs for the JAIL README and the website handoff copy. All images show fictional **Jordan Lee** demo data (see [`../examples/jordan-lee-demo/`](../examples/jordan-lee-demo/)).

## Rules

- **Synthetic content only.** Never commit a screenshot containing real candidate data, real companies, real URLs, or anyone's real job search.
- Screenshots of **runtime folders** (`__READY TO REVIEW/`, `05-SUBMITTED-APPLICATIONS/`, the `00-INTAKE` folders) are allowed **only** when populated with synthetic Jordan Lee data; the runtime folders stay gitignored, only the PNG is committed here.
- **Never** commit images from the real-URL smoke test. **Never** fake/mock a product UI — if a shot isn't captured yet, leave it out.

## Contents

| File | Source | Status |
|---|---|---|
| `hero-ranking.png` | **auto-generated** (matplotlib render of the committed `rankings.xlsx`) — the marketing hero, not the literal spreadsheet UI | ✅ added (Unit 5 Phase A) |
| *(everything else)* | **manual capture** by the author (Finder / Claude Code / Numbers·Excel / markdown preview / browser) | ⏳ pending Phase B |

The full per-shot checklist (what to open, what's visible, crop, README vs website, auto vs manual) lives in [`../examples/jordan-lee-demo/screenshots-notes.md`](../examples/jordan-lee-demo/screenshots-notes.md).

## Naming

Use the `[shot: …]` labels referenced by [`../../README.md`](../../README.md) and [`../jail-public-page-copy.md`](../jail-public-page-copy.md) (e.g. `ranking-xlsx.png`, `intake-review.png`, `folder-tree.png`, `hero-ranking.png`).

## Status

Folder scaffolded in **V2.1 Unit 1**. `hero-ranking.png` auto-generated in **V2.1 Unit 5 Phase A**. The manual captures land in **Phase B**. README/website wiring happens **after** the images are selected.
