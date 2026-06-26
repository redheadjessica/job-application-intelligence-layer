# expected-outputs/ — committed synthetic OUTPUTS

> ⚠️ **100% FICTIONAL.** Every file here is output from the synthetic **Jordan Lee** demo run (persona: AI Product Marketing / GTM). No real candidate, company, or job. See [`../README.md`](../README.md) for the full safety rules.

These are the public-safe artifacts from one end-to-end synthetic run on the **06-25-26** demo batch (5 job posts → 4 ranked + 1 quarantined → 2 tailored → 1 archived → 1 reconciled). They double as the screenshot subjects and as "golden" reference output.

## Provenance — what was *really run* vs *hand-curated*

The user asked for this to be explicit. Honest labels:

| Artifact | What it is | How it was produced |
|---|---|---|
| `rankings.csv` | the ranked job table (durable source) | **Real `vet-jobs` workflow** — LLM scored the 4 usable posts; final-score/status computed by the workflow |
| `rankings.xlsx` | the colored tracker spreadsheet (**the product artifact + the screenshot/hero subject**) | **Real `03-VETTING/make_rankings_xlsx.py`** rendered it from `rankings.csv` + `jail.config.json` (candidate-relative comp/location colors) |
| `rankings.md` | readable markdown rankings | **Real `vet-jobs` workflow** |
| `prep-report.md` | prep summary (usable / thin / failed / dupes) | **Hand-curated** to match `02-PREP/prep_common.py`'s exact output format. Prep was **not** run on the synthetic local posts; live fetch is the separate, disposable Unit 6 real-URL smoke test |
| `prep-manifest.json` | machine-readable prep manifest | **Hand-curated** to the real manifest schema |
| `tailored - Thornbury (strong fit).md` | tailored draft + "Questions for the candidate" (happy path: "None — straightforward fit") | **Real `job-applier` agent** (via `tailor-jobs`) |
| `tailored - Lyceum AI (truth-firewall).md` | tailored draft with **6** honesty questions (weak-evidence role) | **Real `job-applier` agent** — shows the truth-firewall refusing to overclaim |
| `Jordan Lee - Resume - Thornbury - FINAL.pdf` | the synthetic *final submitted* resume | **Hand-curated** (reportlab) — Jordan's resume with **3 deliberate edits vs the agent's recommendation** (used Summary Option 2, softened the AI bullet, dropped one skill) so `/reconcile` has real observed changes |
| `archive-summary.md` | the archived-application record | **`/archive` executed per the skill spec** (config-aware path, move-not-copy) |
| `reconcile-report - Thornbury.md` | per-application learning report | **Real `reconcile` workflow** — correctly observed all the planted diffs and proposed gated lessons |
| `learning-ledger.md` | durable lessons ledger | **Real `reconcile` workflow** (synthesis stage; created from template) |
| `source-update-queue.md` | gated source-update proposals | **Real `reconcile` workflow** (synthesis stage; created from template) |

> **V2.2 regeneration (2026-06-26).** The rankings output was reworked into a job-search **tracker**. `rankings.csv` / `.md` / `.xlsx` were **regenerated deterministically** into the new 23-column shape: human-editable columns first; **`Lane`** = the job's own category, **`Lane Fit`** = the candidate-relative mapping (so Lyceum is now `Lane = "Product Strategy / AI Research"` + `Lane Fit = "Outside lanes (high)"`, no longer a forced "AI Product Marketing"); a sortable job table (no merged cells in the data) with an inline **Status dropdown**, **auto-filter**, frozen header, and wrapped/centered cells; a separate **section-color legend** block below the jobs; an **Instructions** tab; `Category` and `ClaudeStatus` columns removed. **The scores are unchanged** — still the ones the real `vet-jobs` LLM run produced. (There is no auto-rendered marketing hero — the `rankings.xlsx` screenshot is the hero.)

**Intake** (not in this folder): the source-of-truth instances + the `06-25-26 - Intake Review/` folder were generated per the `/intake` spec by a subagent on the synthetic fixtures. They are gitignored runtime instances (local only).

## Regenerating the hero spreadsheet
The `.xlsx` is a deterministic render of `rankings.csv`. To refresh it:

```
.venv/bin/python 03-VETTING/make_rankings_xlsx.py \
  "docs/examples/jordan-lee-demo/expected-outputs/rankings.csv" \
  "docs/examples/jordan-lee-demo/expected-outputs/rankings.xlsx" \
  --config jail.config.json --quarantined 1
```

(Comp/location colors come from a `jail.config.json` matching the fixtures: target 215 / floor 180, NYC home metro.)

## Ranking outcome (designed contrast, real scores)
Thornbury **93** (Apply ASAP, 🟢comp/🟢loc, Lane 🟢 AI PMM) · Flintlock **64** (Backup, 🟢comp/🔴loc, Lane 🟢 AI PMM) · Lanternleaf **62** (Backup, 🔴comp/🟢loc, Lane 🟡 GTM) · Lyceum AI **33** (Or Skip It — green comp+loc but weak fit; Lane 🔴 "Product Strategy / AI Research" → "Outside lanes (high)") · Hatchwing **quarantined**.

## Notes
- Captured **2026-06-25** on branch `v2.1-synthetic-demo-kit`. Two tailored drafts are included; the demo can ship one or both.
- All metrics in these files are directional/fictional. All companies are invented; all URLs are `example.com`.
