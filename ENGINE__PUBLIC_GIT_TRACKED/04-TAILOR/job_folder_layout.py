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


def find_agent_artifact(folder, *relnames):
    """First existing <folder>/<work dir>/<relname> across both work-dir spellings, else None.
    Multiple relnames are tried in preference order within each directory."""
    folder = Path(folder)
    for name in AGENT_WORK_DIRS:
        for rel in relnames:
            p = folder / name / rel
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
    return find_agent_artifact(folder, "final.md")


def resume_base_comparison(folder):
    """The tailoring step's base-vs-improved sidecar, or None. Current name in the work dir;
    legacy `comparison.json` in the work dir, then at the folder root (pre-work-dir folders)."""
    folder = Path(folder)
    found = find_agent_artifact(folder, "resume_base_comparison.json", "comparison.json")
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
    candidates = [(folder / name, "coverletter_agent_output - *.md") for name in AGENT_WORK_DIRS]
    candidates.append((folder, "application_coverletter_output - *.md"))
    for d, pattern in candidates:
        if d.is_dir():
            hits = sorted(d.glob(pattern), key=lambda p: (bool(VERSION_SUFFIX_RE.search(p.stem)), p.name))
            if hits:
                return hits[0]
    return None
