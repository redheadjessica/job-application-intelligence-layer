#!/usr/bin/env python3
"""Back-fill existing job folders into the lane layout (2026-08-06).

Moves agent working artifacts into `_JAIL Agent Work/<lane>/`, folds reconcile's pre-lane
top-level `_extracted/` into the Reconcile lane, and renames the agent `.docx` to
`Cover-Letter-Draft - <Company - Role>.docx`.

Readers already handle every historical shape, so this is cosmetic — nothing breaks if a folder
is never migrated, and nothing breaks if a folder is half-migrated. That is what makes it safe to
run in pieces.

**Nothing ever moves outside its own job folder.** The worst possible outcome is files shuffled
within one folder, which a human can undo by hand. Every rule below exists to keep it that way.

    # see the plan, change nothing (default)
    .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/migrate_job_folder_layout.py "<root>"
    # do it
    .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/migrate_job_folder_layout.py "<root>" --apply
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "03-VETTING"))

from job_folder_layout import (  # noqa: E402
    AGENT_WORK_DIRS,
    LANE_COVER_LETTER,
    LANE_RECONCILE,
    LANE_RESUME,
    LEGACY_EXTRACTION_DIR,
    WORK_DIR,
    work_dir_for_write,
)

# Which lane each artifact belongs to, matched by EXACT name or an explicit glob. Never a loose
# pattern: real folders contain `eval-rubric.md`, `eval-1__draft-v1-ARCHIVED.md`,
# `draft-v4-jessica-handwritten.md` and `final-v2-proposal.md`, every one of which a sloppy
# `eval-*` / `final-*` glob would swallow or rename into nonsense.
EXACT_LANE = {
    "final.md": LANE_COVER_LETTER,
    "resume_base_comparison.json": LANE_RESUME,
    "comparison.json": LANE_RESUME,
}
# Versioned chain files, matched by ANCHORED regex on the stem — a "draft-v*.md" glob also
# matches "draft-v4-jessica-handwritten.md", and "final-v*.md" matches "final-v2-proposal.md".
# Both exist in the real archive and neither is an agent artifact.
STEM_LANE_RES = [
    (re.compile(r"^draft-v\d+$"), LANE_COVER_LETTER),
    (re.compile(r"^eval-v\d+$"), LANE_COVER_LETTER),
    (re.compile(r"^final-v\d+$"), LANE_COVER_LETTER),
]
# Packets carry an arbitrary "Company - Role" (and an optional " - v2"), so a glob is right here.
GLOB_LANE = [
    ("coverletter_agent_output - *.md", LANE_COVER_LETTER),
    ("application_coverletter_output - *.md", LANE_COVER_LETTER),
]
# `eval-<N>.md` -> `eval-v<N>.md`, anchored so only a bare number qualifies.
EVAL_RENAME_RE = re.compile(r"^eval-(\d+)$")
# Legacy names that also get their current spelling while being filed.
RENAME_ON_MOVE = {"comparison.json": "resume_base_comparison.json"}
COVERLETTER_PACKET_PREFIX = ("application_coverletter_output - ", "coverletter_agent_output - ")

# The candidate half of an old .docx name: "<Anything>-Cover-Letter - <Company - Role>.docx".
DOCX_RE = re.compile(r"^.*?[\s\-_]*cover[\s\-_]*letter\s+-\s+(?P<rest>.+)$", re.I)
DRAFT_PREFIX = "Cover-Letter-Draft - "

# Directories whose whole value is being an unchanged snapshot. Migrating a folder named
# "pre-folder-rename" defeats the only reason it exists.
EXCLUDED_DIR_NAMES = {"_backups"}

# How recent a "conflicted copy" has to be to mean "a sync is in flight right now".
CONFLICT_WINDOW_S = 7 * 24 * 60 * 60

# Top-level files that are the candidate's, not the pipeline's. Never touched.
PROTECTED_SUFFIXES = {".pdf", ".pages", ".docx", ".doc", ".txt"}
PROTECTED_PREFIXES = ("application_resume_output - ", "reconcile-report - ")


class Skip(Exception):
    """Abandon this folder entirely. A half-moved folder is worse than an untouched one."""


def is_job_folder(d):
    """A directory is a job folder iff it DIRECTLY holds pipeline evidence. Never infer from a
    name: the archive is full of unrelated directories with `.docx` files in them."""
    if any((d / w).is_dir() for w in AGENT_WORK_DIRS):
        return True
    if (d / LEGACY_EXTRACTION_DIR / "MANIFEST.txt").is_file():
        return True
    return any(d.glob("application_resume_output - *.md"))


def find_job_folders(root):
    """Walk down to each job folder and stop there. `.pages` bundles are directories on macOS —
    descending into one would treat its internals as a folder to migrate."""
    out = []

    # Directories that belong to a job folder rather than containing one.
    interior = {*AGENT_WORK_DIRS, LEGACY_EXTRACTION_DIR}

    def walk(d):
        if d.name.endswith(".pages") or d.name.startswith(".") or d.name in EXCLUDED_DIR_NAMES:
            return
        if d.name in interior:
            return
        if is_job_folder(d):
            out.append(d)
            # Do NOT stop here. A folder covering two roles at one company holds the first
            # role's artifacts at its top level and the second in a subfolder — stopping at the
            # first match leaves the nested role permanently unmigrated.
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir())
        except OSError:
            return
        for c in children:
            walk(c)

    walk(Path(root))
    return out


def _lane_for(name):
    if name in EXACT_LANE:
        return EXACT_LANE[name]
    stem = name[:-3] if name.endswith(".md") else name
    if EVAL_RENAME_RE.match(stem):
        return LANE_COVER_LETTER
    if name.endswith(".md"):
        for rx, lane in STEM_LANE_RES:
            if rx.match(stem):
                return lane
    for pattern, lane in GLOB_LANE:
        if Path(name).match(pattern):
            return lane
    return None


def _target_name(name):
    """The name the artifact should have once filed."""
    if name in RENAME_ON_MOVE:
        return RENAME_ON_MOVE[name]
    stem = name[:-3] if name.endswith(".md") else name
    m = EVAL_RENAME_RE.match(stem)
    if m:
        return f"eval-v{m.group(1)}.md"
    if name.startswith(COVERLETTER_PACKET_PREFIX[0]):
        return COVERLETTER_PACKET_PREFIX[1] + name[len(COVERLETTER_PACKET_PREFIX[0]):]
    return name


def _docx_target(name):
    """`<Name>-Cover-Letter - <Company - Role>.docx` -> `Cover-Letter-Draft - <Company - Role>.docx`."""
    if not name.lower().endswith(".docx") or name.startswith(DRAFT_PREFIX):
        return None
    m = DOCX_RE.match(name[: -len(".docx")])
    return f"{DRAFT_PREFIX}{m.group('rest').strip()}.docx" if m else None


def plan_folder(folder):
    """Every move for this folder, or raise Skip. Sources are validated before anything runs."""
    moves = []

    def add(src, dst):
        if src.is_symlink():
            raise Skip(f"symlink: {src.name}")
        if not src.is_file():
            raise Skip(f"not a regular file: {src.name}")
        # Containment: the whole safety argument rests on this.
        if folder not in dst.parents:
            raise Skip(f"destination escapes the job folder: {dst}")
        if dst.exists():
            raise Skip(f"destination already exists: {dst.relative_to(folder)}")
        if any(d == dst for _, d in moves):
            raise Skip(f"two sources want {dst.relative_to(folder)}")
        moves.append((src, dst))

    # 1. flat work-dir files -> their lane
    for wd in AGENT_WORK_DIRS:
        d = folder / wd
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.is_dir() or p.name.startswith("."):
                continue
            lane = _lane_for(p.name)
            if not lane:
                continue                      # unrecognized: leave it exactly where it is
            add(p, work_dir_for_write(folder) / lane / _target_name(p.name))

    # 2. reconcile's pre-lane extraction
    ex = folder / LEGACY_EXTRACTION_DIR
    if ex.is_dir():
        for p in sorted(ex.iterdir()):
            if p.is_dir() or p.name.startswith("."):
                continue
            add(p, work_dir_for_write(folder) / LANE_RECONCILE / p.name)

    # 3. root-level legacy sidecars
    for name in ("comparison.json",):
        p = folder / name
        if p.is_file():
            add(p, work_dir_for_write(folder) / LANE_RESUME / RENAME_ON_MOVE[name])
    for p in sorted(folder.glob("application_coverletter_output - *.md")):
        add(p, work_dir_for_write(folder) / LANE_COVER_LETTER / _target_name(p.name))

    # 4. the .docx rename, in place at the top level
    for p in sorted(folder.glob("*.docx")):
        tgt = _docx_target(p.name)
        if tgt and tgt != p.name:
            add(p, folder / tgt)

    return moves


def migrate(root, apply=False, out=print):
    root = Path(root).expanduser()
    if not root.is_dir():
        out(f"not a directory: {root}")
        return 2
    # A mass move during a Dropbox sync multiplies conflicts instead of resolving them. What
    # matters is whether a sync is happening NOW — a decade-old "conflicted copy" left in some
    # unrelated folder says nothing about that, and refusing on it just blocks the run forever.
    fresh = []
    for c in root.rglob("*conflicted copy*"):
        try:
            if time.time() - c.stat().st_mtime < CONFLICT_WINDOW_S:
                fresh.append(c)
        except OSError:
            continue
    if fresh:
        out(f"REFUSING: {len(fresh)} recent sync conflict(s) under {root}, e.g. {fresh[0].name}.")
        out("Let the folder finish syncing and resolve the conflict(s) first.")
        return 2

    folders = find_job_folders(root)
    migrated = current = skipped = 0
    for folder in folders:
        rel = folder.relative_to(root)
        try:
            moves = plan_folder(folder)
        except Skip as e:
            out(f"  SKIP  {rel} — {e}")
            skipped += 1
            continue
        if not moves:
            current += 1
            continue
        out(f"  {'MOVE' if apply else 'PLAN'}  {rel}  ({len(moves)} file(s))")
        for src, dst in moves:
            out(f"          {src.name}  ->  {dst.relative_to(folder)}")
        if apply:
            for src, dst in moves:
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.rename(dst)
        migrated += 1

    verb = "migrated" if apply else "would migrate"
    out(f"\n{len(folders)} job folder(s): {migrated} {verb}, {current} already current, {skipped} skipped")
    if not apply and migrated:
        out("Dry run — nothing changed. Re-run with --apply.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", help="directory to scan for job folders")
    ap.add_argument("--apply", action="store_true", help="perform the moves (default: dry run)")
    a = ap.parse_args(argv)
    return migrate(a.root, apply=a.apply)


if __name__ == "__main__":
    raise SystemExit(main())
