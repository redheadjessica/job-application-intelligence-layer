#!/usr/bin/env python3
"""JAIL changelog synthesis.

Rough changelog entries (added by a human or a coding agent during normal work, see
CLAUDE.md -> "Repo changelog") are the primary source; Git history is supporting
evidence for verification and filling genuine gaps.

Synthesis itself is performed by whichever coding agent (Claude Code, Codex, etc.) the
user asks to run it, inside their own session — this script never calls any AI API.
It only does the deterministic parts: gathering evidence, validating/normalizing
structure, and managing the processed-through marker. Stdlib only.

Usage:
    python3 scripts/doc_synthesis.py --mark-current   # establish/advance the baseline
    python3 scripts/doc_synthesis.py --normalize-only # structure/ordering check
    python3 scripts/doc_synthesis.py                  # print evidence for an agent to
                                                       # consolidate, or confirm no-op
    python3 scripts/doc_synthesis.py --force          # print evidence even with no
                                                       # meaningful diff
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from doc_synthesis_core import (  # noqa: E402
    get_processed_commit,
    meaningful_changed_files,
    normalize_changelog,
    set_processed_commit,
)

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"

FORCE = "--force" in sys.argv
MARK_CURRENT = "--mark-current" in sys.argv
NORMALIZE_ONLY = "--normalize-only" in sys.argv

PATHS = {
    "changelog": DOCS_DIR / "changelog.md",
    "workflow": DOCS_DIR / "v2-end-to-end-workflow.md",
}


def read_doc(path: Path):
    return path.read_text(encoding="utf8") if path.exists() else None


def write_doc(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf8")
    print(f"✓ Wrote {path.relative_to(ROOT)}")


def run_git(args: list) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def current_commit() -> str:
    return run_git(["rev-parse", "HEAD"])


def ensure_commit_exists(commit: str) -> None:
    try:
        run_git(["cat-file", "-e", f"{commit}^{{commit}}"])
    except subprocess.CalledProcessError:
        raise RuntimeError(
            f"The changelog marker points to {commit}, which is not available in this "
            "Git history. Run with --mark-current to establish a new baseline."
        )


def collect_git_evidence(base_commit: str, head_commit: str) -> dict:
    ensure_commit_exists(base_commit)
    rng = f"{base_commit}..{head_commit}"
    files = [f for f in run_git(["diff", "--name-only", rng]).splitlines() if f]
    meaningful_files = meaningful_changed_files(files)

    log = ""
    if meaningful_files:
        log = run_git(
            [
                "log",
                "--date=short",
                "--format=commit %H%nDate: %ad%nSubject: %s",
                "--name-status",
                rng,
                "--",
                *meaningful_files,
            ]
        )

    diff = ""
    if meaningful_files:
        diff = run_git(["diff", "--unified=1", rng, "--", *meaningful_files])

    return {
        "base_commit": base_commit,
        "head_commit": head_commit,
        "files": files,
        "meaningful_files": meaningful_files,
        "log": log,
        "diff": diff,
    }


def print_evidence(changelog: str, evidence: dict) -> None:
    print(
        f"→ {len(evidence['meaningful_files'])} meaningful changed file(s) since "
        f"{evidence['base_commit'][:12]} (now at {evidence['head_commit'][:12]}):"
    )
    for f in evidence["meaningful_files"]:
        print(f"    {f}")

    print("\n--- Commit log (meaningful files only) ---")
    print(evidence["log"] or "(none)")

    print("\n--- Diff (meaningful files only) ---")
    print(evidence["diff"] or "(none)")

    print("\n--- Current changelog ---")
    print(changelog)

    print(
        "\n→ Next: consolidate the rough entries above into readable change threads "
        "directly in docs/changelog.md (preserve already-curated older history), "
        "update docs/v2-end-to-end-workflow.md from the curated changelog if it "
        "changed meaningfully, then run:\n"
        "    python3 scripts/doc_synthesis.py --normalize-only\n"
        "    python3 scripts/doc_synthesis.py --mark-current"
    )


def main() -> int:
    changelog = read_doc(PATHS["changelog"])
    if changelog is None:
        raise RuntimeError("docs/changelog.md was not found.")

    normalized = normalize_changelog(changelog)
    head_commit = current_commit()

    if MARK_CURRENT:
        write_doc(PATHS["changelog"], normalize_changelog(set_processed_commit(normalized, head_commit)))
        print(f"✓ Changelog baseline set to {head_commit[:12]}")
        return 0

    if NORMALIZE_ONLY:
        if normalized == changelog:
            print("✓ Changelog structure is normalized; no changes needed.")
        else:
            write_doc(PATHS["changelog"], normalized)
        return 0

    base_commit = get_processed_commit(changelog)
    if not base_commit:
        raise RuntimeError(
            "No changelog baseline marker exists. Review the current changelog, then "
            "run with --mark-current once."
        )

    evidence = collect_git_evidence(base_commit, head_commit)
    if not FORCE and not evidence["meaningful_files"]:
        if normalized != changelog:
            write_doc(PATHS["changelog"], normalized)
        print("✓ No new product, exploration, or documentation changes to synthesize.")
        return 0

    print_evidence(normalized, evidence)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001
        print(f"✗ {error}", file=sys.stderr)
        sys.exit(1)
