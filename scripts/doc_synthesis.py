#!/usr/bin/env python3
"""JAIL documentation synthesis.

The changelog is edited as human-readable project history, not compressed by age or
forced into one entry per day. Granular entries (added by a human or a coding agent
during normal work) are the primary source; Git history is supporting evidence for
verification and filling genuine gaps.

Usage:
    python3 scripts/doc_synthesis.py --mark-current   # establish a safe baseline
    python3 scripts/doc_synthesis.py --normalize-only  # structure check, no AI call
    python3 scripts/doc_synthesis.py --dry-run         # AI pass, no writes
    python3 scripts/doc_synthesis.py                   # live AI pass
    python3 scripts/doc_synthesis.py --force           # force a pass with no meaningful diff
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
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

DRY_RUN = "--dry-run" in sys.argv
VERBOSE = "--verbose" in sys.argv
FORCE = "--force" in sys.argv
MARK_CURRENT = "--mark-current" in sys.argv
NORMALIZE_ONLY = "--normalize-only" in sys.argv

PATHS = {
    "changelog": DOCS_DIR / "changelog.md",
    "workflow": DOCS_DIR / "v2-end-to-end-workflow.md",
    "readme": ROOT / "README.md",
    "doc_status": DOCS_DIR / "doc-status.md",
}


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf8").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip("\"'")


def read_doc(path: Path):
    return path.read_text(encoding="utf8") if path.exists() else None


def write_doc(path: Path, content: str) -> None:
    if DRY_RUN:
        print(f"[dry run] Would write {path.relative_to(ROOT)} ({content.count(chr(10)) + 1} lines)")
        return
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
        "log": log[:16_000],
        "diff": diff[:28_000],
    }


def call_claude(system_prompt: str, user_message: str) -> str:
    import urllib.error
    import urllib.request

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for an AI synthesis pass.")

    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    if VERBOSE:
        print(f"Claude model: {model}")
        print(f"Prompt sizes: system={len(system_prompt)}, user={len(user_message)}")

    payload = json.dumps(
        {
            "model": model,
            "max_tokens": 8192,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }
    ).encode("utf8")

    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            data = json.loads(response.read().decode("utf8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Claude API error {error.code}: {error.read().decode('utf8')}")

    for block in data.get("content", []):
        if block.get("type") == "text":
            return block.get("text", "")
    return ""


def strip_markdown_fence(value: str) -> str:
    value = value.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1] if "\n" in value else ""
    if value.endswith("```"):
        value = value.rsplit("```", 1)[0]
    return value.strip()


def rewrite_changelog(changelog: str, evidence: dict) -> str:
    system = """You edit JAIL's changelog as interesting, human-readable project history.

JAIL is a local, run-it-yourself pipeline (fetch job posts a person supplies -> vet a
batch -> tailor the top few -> learn from what they submit). It never searches for jobs
and never submits an application on the person's behalf.

Editorial rules:
- Organize around meaningful change threads: a feature may span multiple days, and one
  day may contain several distinct entries.
- Use "## YYYY-MM-DD — Title" for one day.
- Use "## YYYY-MM-DD to DD — Title" for a range within one month.
- Use both full dates for a range crossing a month or year.
- There is no fixed bullet count. Use as many as the story warrants, usually 1-8, but
  every bullet must add meaningful information.
- Preserve: what changed and why, the user problem/testing result/confusion/failure that
  prompted it, privacy/trust/provenance/control concerns (JAIL is privacy-sensitive: the
  three-root gitignore split, the never-submit boundary, the pre-commit denylist
  firewall), architectural simplifications, decisions to remove complexity, cases where
  actual use contradicted the initial design, meaningful changes in how the human and
  coding agents interact, and explorations that produced a useful conclusion even when
  they did not directly ship.
- Describe the lasting outcome rather than narrating every intermediate attempt or
  restructuring commit.
- Drop routine test counts, file inventories, debug fields, tiny polish iterations, and
  superseded implementation attempts that later work replaced.
- Granular changelog entries are the primary account. Use Git evidence to verify claims
  and fill genuine gaps, not to turn the changelog into a commit log.
- Keep the historical "Pre-history" and "Earlier" sections intact unless new evidence
  directly corrects them.
- Treat the result as public: generalize private personal examples and omit secrets,
  credentials, API keys, or unnecessary personal data (this repo's own guardrail: never
  named companies/people from a user's real job search, only the pattern a change
  addresses).
- Preserve the document preamble and the hidden changelog-processed-through marker.
- Return the complete Markdown document only, without a code fence or explanation."""

    user = f"""Current curated changelog:
<changelog>
{changelog}
</changelog>

Git evidence since {evidence['base_commit']}:
<commit_log>
{evidence['log'] or 'No commit messages in range.'}
</commit_log>

Meaningful changed files:
{chr(10).join(evidence['meaningful_files']) or 'None'}

Supporting diff excerpt (may be truncated):
<diff>
{evidence['diff'] or 'No meaningful product diff in range.'}
</diff>

Update only what the new work warrants. Preserve already-curated older history."""

    return strip_markdown_fence(call_claude(system, user))


def update_workflow_doc(changelog: str, existing_workflow):
    today = date.today().isoformat()
    system = f"""Update JAIL's current-state workflow reference (docs/v2-end-to-end-workflow.md)
from its curated changelog. Describe current reality: the three-root layout
(ENGINE__PUBLIC_GIT_TRACKED / PRIVATE__YOUR_FILES_GITIGNORED /
__READY_TO_REVIEW__PRIVATE_GITIGNORED), the pipeline stages, and what is live, partial,
or exploratory. Correct superseded information, but do not invent features or stages
that the changelog does not support. Keep the document's existing structure and
Mermaid diagrams where still accurate. Return the complete Markdown document only,
without a code fence or explanation. Set any "last updated" note to {today} if the
document has one."""
    user = f"""Existing workflow doc:
{existing_workflow if existing_workflow is not None else "(Not available — report that no current-state doc exists rather than inventing one.)"}

Curated changelog:
{changelog}"""
    return strip_markdown_fence(call_claude(system, user))


def check_for_drift(changelog: str, readme):
    today = date.today().isoformat()
    system = f"""Check README.md's "Repo layout" and pipeline description against JAIL's
curated changelog. Report only concrete discrepancies. Absence from the changelog is
not proof of drift. Use this Markdown structure:
## Drift Report — {today}
### README.md
- ...
### Recommended actions
- ..."""
    user = f"""Curated changelog:
{changelog}

README.md:
{readme if readme is not None else "(Not available.)"}"""
    return strip_markdown_fence(call_claude(system, user))


def build_doc_status(drift_report: str) -> str:
    today = date.today().isoformat()
    return f"""# JAIL — Doc Status

> Last synthesis pass: {today}
> Run `python3 scripts/doc_synthesis.py` to refresh.

## Last Drift Report

{drift_report}
"""


def main() -> int:
    load_env()
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

    print(
        f"→ Synthesizing {len(evidence['meaningful_files'])} meaningful changed file(s) "
        f"from {base_commit[:12]} to {head_commit[:12]}..."
    )

    rewritten = rewrite_changelog(normalized, evidence)
    new_changelog = normalize_changelog(set_processed_commit(rewritten, head_commit))
    existing_workflow = read_doc(PATHS["workflow"])
    readme = read_doc(PATHS["readme"])

    updated_workflow = update_workflow_doc(new_changelog, existing_workflow)
    drift_report = check_for_drift(new_changelog, readme)

    write_doc(PATHS["changelog"], new_changelog)
    if existing_workflow is not None:
        write_doc(PATHS["workflow"], updated_workflow)
    write_doc(PATHS["doc_status"], build_doc_status(drift_report))
    print("✓ Dry run complete; no files were changed." if DRY_RUN else "✓ Documentation synthesis complete.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001
        print(f"✗ Synthesis failed: {error}", file=sys.stderr)
        if VERBOSE:
            raise
        sys.exit(1)
