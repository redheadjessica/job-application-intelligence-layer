#!/usr/bin/env python3
"""Re-render the capture-history sections of saved captures from the durable registry.

Why this exists: a staging/canary worker writes into an ISOLATED registry shard — that
isolation is required (a rejected staging capture must never become the permanent
original), but an empty shard leaves the writer with no history to render, so each staged
file writes its OWN fetch as `ORIGINAL CAPTURE DETAILS` with no `LATEST` section. The
artifact then claims today's fetch is the original and drops the true history, even though
the global registry is correct. This restores the file to what the durable record says.

A re-render is NOT a capture event: no request is made, no history is appended, no
timestamp moves, and the registry file is opened READ-ONLY. Everything above
`--- JOB TEXT END ---` — snapshot, work details, compensation, questions, and the job text
itself — is preserved byte-for-byte; only the capture-details tail is rewritten.

Usage (after merging staged shards into the global registry):

    python ENGINE__PUBLIC_GIT_TRACKED/02-PREP/apply_registry_history.py \\
        "<batch>/3 - Source Material/All Job Posts (full text)"

    # preview without writing
    python ENGINE__PUBLIC_GIT_TRACKED/02-PREP/apply_registry_history.py <folder> --dry-run

    # against a specific registry (default: JAIL_CAPTURE_REGISTRY, else the global file)
    python ENGINE__PUBLIC_GIT_TRACKED/02-PREP/apply_registry_history.py <folder> \\
        --registry /path/to/capture-history-registry.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prep_common import (  # noqa: E402
    apply_registry_history,
    capture_identity_from_file,
    load_capture_registry,
    render_capture_history,
    resolve_registry_path,
)


def _capture_files(targets) -> list[Path]:
    out: list[Path] = []
    for target in targets:
        p = Path(target)
        if p.is_dir():
            out.extend(sorted(f for f in p.rglob("*.txt") if f.is_file()))
        elif p.is_file():
            out.append(p)
    return out


def run(targets, registry_path=None, dry_run: bool = False, out=print) -> dict:
    reg_path = resolve_registry_path(registry_path)
    registry = load_capture_registry(reg_path)
    postings = registry.get("postings") or {}
    counts = {"changed": 0, "unchanged": 0, "not_in_registry": 0, "unreadable": 0}
    for path in _capture_files(targets):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            counts["unreadable"] += 1
            out(f"  ? {path.name}: unreadable")
            continue
        key = capture_identity_from_file(text)
        posting = postings.get(key) if key else None
        if not key or not posting or not posting.get("original_capture"):
            counts["not_in_registry"] += 1
            out(f"  – {path.name}: no registry record ({key or 'no identity'}) — left untouched")
            continue
        if dry_run:
            changed = render_capture_history(text, posting) != text
        else:
            changed = apply_registry_history(path, reg_path)
        counts["changed" if changed else "unchanged"] += 1
        if changed:
            orig = (posting.get("original_capture") or {}).get("fetched_at")
            latest = (posting.get("latest_capture") or {}).get("fetched_at")
            out(f"  ✓ {path.name}: original {orig}"
                + (f" · latest {latest}" if latest and latest != orig else " (first capture)"))
    out(f"[apply-registry-history] registry: {reg_path}")
    out(f"[apply-registry-history] {counts['changed']} rewritten, "
        f"{counts['unchanged']} already correct, "
        f"{counts['not_in_registry']} without a registry record, "
        f"{counts['unreadable']} unreadable."
        + ("  (dry run — nothing written)" if dry_run else ""))
    return counts


def main(argv):
    parser = argparse.ArgumentParser(
        description="Re-render capture-history sections from the durable registry.")
    parser.add_argument("targets", nargs="+",
                        help="capture files and/or folders to scan (recursively)")
    parser.add_argument("--registry", default=None,
                        help="registry file to read (default: JAIL_CAPTURE_REGISTRY, "
                             "else the global gitignored registry)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    args = parser.parse_args(argv[1:])
    run(args.targets, registry_path=args.registry, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
