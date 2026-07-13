# JAIL Changelog

Project changelog. Reverse chronological. Maintained as readable project memory: what
changed, what was explored, and why it mattered — not a commit log. Git history already
holds the granular record; this file is the curated account.

Add rough entries here during normal work (see `scripts/README.md` for the format).
Run `python3 scripts/doc_synthesis.py` to consolidate them into readable threads.


<!-- changelog-processed-through: bd576955caf6495566fc88fcf9b7b5aadb8d10c8 -->
---

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

## Pre-2026-07-13 — Everything before the changelog existed

- JAIL shipped its V2 pipeline (Prep → Vet → Tailor → Reconcile/Archive) and the
  three-root layout (`ENGINE__PUBLIC_GIT_TRACKED` / `PRIVATE__YOUR_FILES_GITIGNORED` /
  `__READY_TO_REVIEW__PRIVATE_GITIGNORED`) before this changelog began. See
  `docs/v2-end-to-end-workflow.md` and `docs/testing-and-caveats.md` for that history.

## Earlier — Origins

- The project began as a single-purpose resume tailoring helper and grew into the full
  chained pipeline described in `README.md`.
