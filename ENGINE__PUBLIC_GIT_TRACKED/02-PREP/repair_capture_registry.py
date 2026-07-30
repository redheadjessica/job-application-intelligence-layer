#!/usr/bin/env python3
"""Canonicalize the capture-history registry's posting identities (idempotent).

Why this exists: the same posting can enter the registry under different key forms —
a raw employer URL (`lark.com/careers/open-positions?ashby_jid=<id>`) beside its ATS
identity (`ashby:lark:<id>`) was the live defect, and the split history mislabeled
ORIGINAL until it was merged by hand. Every registry WRITE now canonicalizes (and
follows recorded aliases), so new duplicates cannot form; this CLI repairs a registry
that already contains them.

Per posting, the canonical identity is recomputed from the posting's OWN recorded
events. An alias-keyed posting is folded into its canonical one under the registry's
invariants — history unioned and deduped, the EARLIEST original wins and stays
immutable, latest advances only to the newest successful event — and the old key is
recorded as an alias so future writes under it land on the canonical posting. Two
different ATS identities among one posting's events is an UNRESOLVED CONFLICT: it is
reported and left untouched, never silently merged.

Safety: `--dry-run` reports without writing; a real run writes a timestamped BACKUP
of the registry beside it before mutating, and the write itself is atomic and
lock-guarded. Never destructive without the backup. Running it twice reports zeros.

    python ENGINE__PUBLIC_GIT_TRACKED/02-PREP/repair_capture_registry.py --dry-run
    python ENGINE__PUBLIC_GIT_TRACKED/02-PREP/repair_capture_registry.py \\
        --registry /path/to/capture-history-registry.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prep_common import (  # noqa: E402
    atomic_write_text,
    canonicalize_registry,
    file_lock,
    load_capture_registry,
    resolve_registry_path,
)


def run(registry_path=None, dry_run: bool = False, out=print) -> dict:
    reg_path = resolve_registry_path(registry_path)
    registry = load_capture_registry(reg_path)
    before = len(registry.get("postings") or {})
    counts = canonicalize_registry(registry, out=out)
    counts["postings_before"] = before
    counts["postings_after"] = len(registry.get("postings") or {})
    changed = counts["aliases_discovered"] or counts["identities_merged"]
    if changed and not dry_run:
        backup = reg_path.with_name(
            f"{reg_path.name}.backup-{time.strftime('%Y%m%dT%H%M%S')}")
        shutil.copy2(reg_path, backup)
        out(f"[registry-repair] backup written: {backup}")
        counts["backup"] = str(backup)
        with file_lock(reg_path):
            atomic_write_text(reg_path, json.dumps(registry, indent=2) + "\n")
        out(f"[registry-repair] registry written: {reg_path}")
    out(f"[registry-repair] {counts['aliases_discovered']} alias(es) discovered, "
        f"{counts['identities_merged']} identity merge(s), "
        f"{counts['unresolved_conflicts']} unresolved conflict(s); "
        f"{counts['postings_before']} -> {counts['postings_after']} posting(s)."
        + ("  (dry run — nothing written)" if dry_run else
           ("" if changed else "  (already canonical — nothing to write)")))
    return counts


def main(argv):
    parser = argparse.ArgumentParser(
        description="Canonicalize registry posting identities (idempotent; backs up "
                    "before any mutation).")
    parser.add_argument("--registry", default=None,
                        help="registry file (default: JAIL_CAPTURE_REGISTRY, else the "
                             "global gitignored registry)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    args = parser.parse_args(argv[1:])
    counts = run(registry_path=args.registry, dry_run=args.dry_run)
    return 1 if counts["unresolved_conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
