# JAIL — Repo Scripts

Repo-maintenance scripts. Not part of the job-application pipeline itself.

---

## doc_synthesis.py

Turns rough, in-the-moment changelog entries plus Git history into readable project
memory, and keeps `docs/v2-end-to-end-workflow.md` in sync with what actually shipped.

### Adding a rough entry during normal work

While making a meaningful change, add a short dated bullet (or a new `## YYYY-MM-DD —
Title` section if none exists yet for today) directly to `docs/changelog.md`, above the
`<!-- changelog-processed-through -->` marker. Rough and unpolished is fine — synthesis
cleans it up later. Skip trivial edits (typos, formatting, comment-only changes).

### Running synthesis

```bash
# One-time setup after manually approving the current changelog
python3 scripts/doc_synthesis.py --mark-current

# Structure and ordering check only — no AI call
python3 scripts/doc_synthesis.py --normalize-only

# Live AI run — consolidates entries, writes docs/changelog.md,
# docs/v2-end-to-end-workflow.md, and docs/doc-status.md
python3 scripts/doc_synthesis.py

# AI run without writing anything
python3 scripts/doc_synthesis.py --dry-run

# Verbose — show Claude prompt sizes and model used
python3 scripts/doc_synthesis.py --verbose

# Force a pass even when Git finds no meaningful changed files
python3 scripts/doc_synthesis.py --force
```

### Requirements

- Python 3.9+ (stdlib only — no new dependency; `requirements.txt` is untouched)
- `ANTHROPIC_API_KEY` set in your environment or a `.env` file at the repo root, for AI
  passes only (`--normalize-only` and `--mark-current` never call the API)
- Optional `ANTHROPIC_MODEL` override; otherwise the current Claude Sonnet is used
- Run from the repo root

### What it writes

| File | What changes |
|---|---|
| `docs/changelog.md` | New rough entries consolidated into readable change threads; processed-commit marker advanced |
| `docs/v2-end-to-end-workflow.md` | Updated from the curated changelog (JAIL's current-state workflow doc) |
| `docs/doc-status.md` | Latest documentation drift report (advisory only) |

### What it does NOT do

- Never modifies `README.md` directly — only flags drift in `docs/doc-status.md`
- Never commits or pushes
- Never invents a stage, feature, or file that the changelog and Git evidence don't
  support
- Performs a true no-op (no file writes, no AI call) when nothing meaningful changed
  since the last processed commit
- Never lets its own maintenance commits (this script, its tests, the changelog, the
  drift report) count as "meaningful work" and re-trigger itself

### Tests

`tests/test_doc_synthesis_core.py` covers the deterministic logic (heading parsing,
sorting, idempotency, marker handling, and the maintenance-commit filter). Run with:

```bash
python3 -m unittest tests.test_doc_synthesis_core -v
```
