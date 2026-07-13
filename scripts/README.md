# JAIL — Repo Scripts

Repo-maintenance scripts. Not part of the job-application pipeline itself.

---

## doc_synthesis.py

Keeps `docs/changelog.md` readable and `docs/v2-end-to-end-workflow.md` current, using
rough changelog entries plus Git history as evidence. **This script never calls an AI
API.** Synthesis (the actual rewrite) is performed by whichever coding agent — Claude
Code, Codex, or otherwise — you ask to run it, inside that agent's own session. The
script only handles the deterministic parts: gathering evidence, validating/sorting
changelog structure, and managing the hidden processed-commit marker.

### Adding a rough entry during normal work

This is not optional — see `CLAUDE.md` → "Repo changelog". While making a meaningful
change, add a short dated bullet (or a new `## YYYY-MM-DD — Title` section if none
exists yet for today) directly to `docs/changelog.md`, above the
`<!-- changelog-processed-through -->` marker. Rough and unpolished is fine — synthesis
cleans it up later. Skip trivial edits (typos, formatting, comment-only changes).

### Requesting synthesis

Synthesis is occasional and user-initiated — nothing runs it automatically. When you
want it, ask an active Claude Code or Codex session something like "run changelog
synthesis" or "consolidate the changelog." The agent should:

```bash
# 1. See what's changed since the last processed commit
python3 scripts/doc_synthesis.py

# 2. Consolidate the printed rough entries into readable change threads directly in
#    docs/changelog.md (preserving already-curated older history), and update
#    docs/v2-end-to-end-workflow.md if the curated changelog changed meaningfully.

# 3. Validate structure and ordering
python3 scripts/doc_synthesis.py --normalize-only

# 4. Advance the baseline once satisfied
python3 scripts/doc_synthesis.py --mark-current
```

Other flags:

```bash
# One-time setup after manually approving the current changelog
python3 scripts/doc_synthesis.py --mark-current

# Print evidence even when Git finds no meaningful changed files
python3 scripts/doc_synthesis.py --force
```

### Requirements

- Python 3.9+ (stdlib only — no dependency, no API key, nothing in `requirements.txt`
  changes for this)
- Run from the repo root

### What it does NOT do

- Never calls any AI API or requires an API key
- Never rewrites the changelog's prose itself — that's the acting agent's job
- Never modifies `README.md` or `docs/v2-end-to-end-workflow.md` directly — the agent
  does that as part of the synthesis pass, if warranted
- Never commits or pushes
- Performs a true no-op (no output beyond a confirmation, no file writes) when nothing
  meaningful changed since the last processed commit
- Never lets its own maintenance commits (this script, its tests, the changelog) count
  as "meaningful work" and re-trigger itself

### Tests

`tests/test_doc_synthesis_core.py` covers the deterministic logic (heading parsing,
sorting, idempotency, marker handling, and the maintenance-commit filter). Run with:

```bash
python3 -m unittest tests.test_doc_synthesis_core -v
```
