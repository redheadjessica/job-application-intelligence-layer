#!/usr/bin/env python3
"""The shape of a job-application folder — the ONE place that knows where artifacts live.

A job folder holds two different kinds of thing, and the split matters:

  <Company - Role - date>/
    <Name>-Resume - X.pages / .pdf / X FULL.pdf   the deliverables, and
    <Name>-CoverLetter - X.pdf                    the things a human reads:
    Cover-Letter-Draft - <Company - Role>.docx    they stay at the top level
    application_resume_output - X.md
    reconcile-report - X - date.md
    <job capture>.txt
    _JAIL Agent Work/                             everything an agent produced to get there
      <lane>/                                     grouped by the agent that produced it

Three consumers depend on this shape — the Python readers, the back-fill migration, and the
agent prompts (via this module's CLI). They must not each carry their own copy of it: that is
how the 2026-08-04 rename ended up with ~30 hardcoded literals spread across JS and Markdown,
none of them covered by a test.

**Back-compat is additive, never substitutive.** Well over a hundred already-submitted folders
sit on disk in older shapes, and they are the learning loop's evidence — reconcile reads them
months after the fact. A reader that stops finding them silently corrupts the loop rather than
failing loudly. So every historical location stays in the search path forever; new locations are
prepended, old ones are never removed.
"""

import re
from pathlib import Path

# --------------------------------------------------------------------------- #
# The work directory. Renamed from "_cl_work" on 2026-08-04 (it had outgrown being
# cover-letter-only). Readers accept both spellings, newest first; writers emit only the new one.
# --------------------------------------------------------------------------- #
WORK_DIR = "_JAIL Agent Work"
LEGACY_WORK_DIRS = ("_cl_work",)
AGENT_WORK_DIRS = (WORK_DIR, *LEGACY_WORK_DIRS)

# The " - v2" / " - v3" revision suffix on a review packet (unchanged by any rename).
VERSION_SUFFIX_RE = re.compile(r" - v\d+$", re.I)

# --------------------------------------------------------------------------- #
# Lanes (2026-08-06). Inside the work directory, artifacts are grouped by the agent that
# produced them. Before this, everything sat in one flat pile and reconcile's extraction lived
# in a separate top-level "_extracted/" whose name said nothing about what made it.
#
# Casing is canonical on write. Compare case-insensitively on read — APFS is case-insensitive,
# so a hand-created "cover letter agent/" IS the same directory, but a literal string comparison
# would miss it.
# --------------------------------------------------------------------------- #
LANE_COVER_LETTER = "Cover Letter Agent"
LANE_RECONCILE = "Reconcile Agent"
LANE_RESUME = "Resume Tailoring Agent"
LANES = (LANE_COVER_LETTER, LANE_RECONCILE, LANE_RESUME)

# The pre-lane home of reconcile's extraction, at the job-folder top level.
LEGACY_EXTRACTION_DIR = "_extracted"

# The sentinel that proves an extraction directory is real and complete.
EXTRACTION_MANIFEST = "MANIFEST.txt"


def search_dirs(folder, lane=None):
    """Directories to search for an artifact, best shape first.

    Order, and why each tier exists:
      1. work dir / lane      the current shape
      2. work dir             flat — the 2026-08-04 shape, still on disk in many folders
      3. legacy work dirs     "_cl_work", same two tiers again
      4. cross-lane           a half-migrated folder is a real state, and no filename collides
                              across lanes, so looking in the wrong lane is unambiguous
    The folder root is NOT included: only two artifacts ever lived there, and they say so
    themselves rather than making every lookup scan the deliverables."""
    folder = Path(folder)
    for wd in AGENT_WORK_DIRS:
        if lane:
            yield folder / wd / lane
        yield folder / wd
    if lane:
        for wd in AGENT_WORK_DIRS:
            for other in LANES:
                if other != lane:
                    yield folder / wd / other


def lane_dir_for_write(folder, lane):
    """Where a writer puts a lane's artifacts: always the current work dir + canonical casing."""
    return work_dir_for_write(folder) / lane


def extraction_dir_for_write(folder):
    """Where reconcile's extraction is written now."""
    return lane_dir_for_write(folder, LANE_RECONCILE)


def extraction_dir_for_read(folder):
    """The extraction directory to READ, or the write path when none exists yet.

    Resolved by the presence of MANIFEST.txt, not by directory existence — an empty lane dir
    left behind by an interrupted run must not read as a completed extraction. This is what the
    cache check depends on: miss it, and every folder still holding a legacy `_extracted/` gets
    re-extracted into a second directory that can then diverge from the first."""
    folder = Path(folder)
    for d in (extraction_dir_for_write(folder), folder / LEGACY_EXTRACTION_DIR):
        if (d / EXTRACTION_MANIFEST).is_file():
            return d
    return extraction_dir_for_write(folder)


def work_dir_for_write(folder):
    """Where a writer creates agent work: ALWAYS the current name.

    Deliberately not `agent_work_dir()`. That one returns the first directory that already
    exists, so on a legacy folder it answers "_cl_work" — fine for reading, wrong for writing,
    since it would keep growing a directory the whole system has moved off of."""
    return Path(folder) / WORK_DIR


def agent_work_dir(folder):
    """The folder's agent-work directory for READING. Returns the first that exists (new name
    preferred), else the new-name path. Use `work_dir_for_write()` when creating anything."""
    folder = Path(folder)
    for name in AGENT_WORK_DIRS:
        if (folder / name).is_dir():
            return folder / name
    return folder / WORK_DIR


def find_agent_artifact(folder, *relnames, lane=None):
    """First existing <search dir>/<relname>, else None. Directories are tried in `search_dirs`
    order (current shape first, historical shapes after); within each, relnames are tried in the
    order given, so a caller can express "current name, then legacy name"."""
    for d in search_dirs(folder, lane):
        for rel in relnames:
            p = d / rel
            if p.is_file():
                return p
    return None


def coverletter_baseline(folder):
    """The frozen cover-letter learning baseline, or None.

    Resolves `final.md` and ONLY `final.md` — never `final-v2.md`. That is not an oversight:
    the baseline is deliberately locked to the FIRST version, because the learning signal is
    "what did the agent write before any human touched it" versus what was actually submitted.
    Globbing `final-v*` here would silently re-baseline against a revision and make every later
    diff measure the wrong thing."""
    return find_agent_artifact(folder, "final.md", lane=LANE_COVER_LETTER)


def resume_base_comparison(folder):
    """The tailoring step's base-vs-improved sidecar, or None. Current name in the work dir;
    legacy `comparison.json` in the work dir, then at the folder root (pre-work-dir folders)."""
    folder = Path(folder)
    found = find_agent_artifact(folder, "resume_base_comparison.json", "comparison.json",
                                lane=LANE_RESUME)
    if found:
        return found
    legacy = folder / "comparison.json"
    return legacy if legacy.is_file() else None


def coverletter_packet(folder):
    """The cover-letter review packet, or None. Current name in the work dir; legacy
    `application_coverletter_output - ….md` at the folder root. The un-versioned ORIGINAL always
    wins over "- v2"/"- v3" revisions — it is the immutable learning baseline, and plain
    name-sorting would pick the wrong one (" - v2.md" sorts BEFORE ".md")."""
    folder = Path(folder)
    candidates = [(d, "coverletter_agent_output - *.md")
                  for d in search_dirs(folder, LANE_COVER_LETTER)]
    candidates.append((folder, "application_coverletter_output - *.md"))
    for d, pattern in candidates:
        if d.is_dir():
            hits = sorted(d.glob(pattern), key=lambda p: (bool(VERSION_SUFFIX_RE.search(p.stem)), p.name))
            if hits:
                return hits[0]
    return None


# --------------------------------------------------------------------------- #
# CLI. Agent prompts call this instead of describing a search order in prose.
#
# A code fallback chain is deterministic; an LLM working through a four-location chain
# written in English is not, and it now has more shapes to consider than a sentence can
# carry reliably. This also means a future shape change edits one file rather than the ~30
# hardcoded literals the 2026-08-04 rename left scattered across JS and Markdown.
# --------------------------------------------------------------------------- #
_ARTIFACTS = {
    "coverletter-baseline": coverletter_baseline,
    "coverletter-packet": coverletter_packet,
    "resume-base-comparison": resume_base_comparison,
    "extraction-dir": extraction_dir_for_read,
}
_LANES_BY_FLAG = {
    "cover-letter": LANE_COVER_LETTER,
    "reconcile": LANE_RECONCILE,
    "resume": LANE_RESUME,
}


def latest_letter(folder):
    """The newest cover letter to revise FROM: highest `final-vN.md`, else `final.md`, else the
    first draft. Distinct from `coverletter_baseline()`, which is deliberately pinned to v1 —
    a revision continues from the newest text, while learning always measures against the first."""
    versioned = []
    for d in search_dirs(folder, LANE_COVER_LETTER):
        if not d.is_dir():
            continue
        for p in d.glob("final-v*.md"):
            m = re.fullmatch(r"final-v(\d+)", p.stem)
            if m:
                versioned.append((int(m.group(1)), p))
    if versioned:
        return max(versioned, key=lambda t: t[0])[1]
    return coverletter_baseline(folder) or find_agent_artifact(
        folder, "draft-v1.md", lane=LANE_COVER_LETTER)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder")
    ap.add_argument("--find", choices=sorted(list(_ARTIFACTS) + ["latest-letter"]),
                    help="print the resolved path (empty if not found)")
    ap.add_argument("--write-dir", choices=sorted(_LANES_BY_FLAG),
                    help="print the directory a writer should create for that lane")
    a = ap.parse_args(argv)
    folder = Path(a.folder).expanduser()
    if a.write_dir:
        print(lane_dir_for_write(folder, _LANES_BY_FLAG[a.write_dir]))
        return 0
    if a.find:
        fn = latest_letter if a.find == "latest-letter" else _ARTIFACTS[a.find]
        found = fn(folder)
        print(found if found else "")
        return 0 if found else 1
    ap.error("pass --find or --write-dir")


if __name__ == "__main__":
    raise SystemExit(main())
