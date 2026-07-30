#!/usr/bin/env python3
"""Seed the durable capture-history registry from existing batch manifests.

Scans a reviews root (default `__READY_TO_REVIEW__PRIVATE_GITIGNORED/`, including
`archive/` and any nested/mirrored batch folders) READ-ONLY for
`prep-manifest.json` files, and replays every dated fetch record into the
gitignored registry in chronological order — so each posting's immutable
`original_capture` lands on the EARLIEST reliable timestamp the durable records
can establish.

Key canonicalization matters here: the OLDEST manifests keyed some postings under
the raw employer URL (e.g. `https://careers.airbnb.com/positions/8044715`) while
newer ones use the ATS identity (`greenhouse:airbnb:8044715`). All alias forms —
already-canonical ATS keys, employer `/positions/<id>` deep links, `?gh_jid=<id>`
query params, plain URLs — resolve through `canonical_capture_key` to ONE
registry key, so the earliest record wins regardless of which form recorded it.
A backfill that only matched already-normalized keys would silently crown a later
fetch as "original".

Backfilled originals are marked `original_source: backfill-earliest-known`: the
human heading "ORIGINAL" in a capture file means "the earliest capture JAIL can
establish from its durable records", not necessarily the true first-ever fetch.

Identical (key, fetched_at, url) events dedupe — mirrored batch folders (e.g. a
`_rescore/` copy of a batch) contribute one event, not two.

Writes ONLY the registry file (gitignored, under the PRIVATE root). Never
modifies a batch, a manifest, or a capture.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prep_common import (  # noqa: E402
    DEFAULT_REGISTRY_PATH,
    FAILED,
    canonical_capture_key,
    load_capture_registry,
    record_capture_event,
    save_capture_registry,
)

# A recognized ATS-identity key stored directly as a manifest normalized_url.
_ATS_KEY_PREFIXES = ("greenhouse:", "ashby:", "lever:", "linkedin:")


def _entry_key(entry: dict) -> str:
    norm = str(entry.get("normalized_url") or "")
    if norm.startswith(_ATS_KEY_PREFIXES):
        return norm
    return canonical_capture_key(entry.get("original_url") or norm,
                                 posting_id=entry.get("posting_id"))


def collect_events(root: Path) -> list[tuple[str, dict, bool, Path]]:
    """Every dated fetch record in every manifest under root, as
    (key, event, success, manifest_path), sorted chronologically."""
    events: list[tuple[str, dict, bool, Path]] = []
    for mpath in sorted(root.rglob("prep-manifest.json")):
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            continue
        for entry in manifest.get("entries") or []:
            fetched_at = entry.get("fetched_at")
            status = entry.get("status")
            if not fetched_at or not status or status == "duplicate":
                continue  # a skipped duplicate is not a capture
            key = _entry_key(entry)
            success = status != FAILED
            event = {
                "fetched_at": fetched_at,
                "url": entry.get("original_url"),
                "normalized_url": entry.get("normalized_url"),
                "batch": manifest.get("batch") or mpath.parent.parent.name,
                "method": entry.get("method"),
                "source": entry.get("method"),
                "posting_id": entry.get("posting_id"),
                "status": status,
                "ok": success,
            }
            events.append((key, event, success, mpath))
    events.sort(key=lambda t: (t[1].get("fetched_at") or "", t[0]))
    return events


def backfill(root: Path, registry_path: Path, *, dry_run: bool = False,
             out=print) -> dict:
    registry = load_capture_registry(registry_path)
    events = collect_events(root)
    for key, event, success, mpath in events:
        before = key in registry.get("postings", {})
        record_capture_event(registry, key, event, success=success,
                             origin="backfill-earliest-known", dedupe=True)
        if not before:
            out(f"[backfill] new posting {key}: earliest known "
                f"{event['fetched_at']}  (from {mpath})")
    out(f"[backfill] {len(events)} event(s) across "
        f"{len(registry.get('postings', {}))} posting(s).")
    if not dry_run:
        save_capture_registry(registry_path, registry)
        out(f"[backfill] registry written: {registry_path}")
    return registry


def main(argv):
    parser = argparse.ArgumentParser(description="Seed the capture-history registry "
                                                 "from existing batch manifests.")
    parser.add_argument("--root", default="__READY_TO_REVIEW__PRIVATE_GITIGNORED",
                        help="reviews root to scan (read-only)")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH),
                        help="registry file to write (gitignored)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv[1:])
    backfill(Path(args.root), Path(args.registry), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
