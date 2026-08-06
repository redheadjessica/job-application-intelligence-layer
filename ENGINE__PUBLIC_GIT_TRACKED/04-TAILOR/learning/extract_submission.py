#!/usr/bin/env python3
"""One-time deterministic extraction of a submitted application folder (reconcile pre-step).

Turns the PDFs in a submitted-application archive folder into cached plain-text artifacts so
reconcile agents never re-read PDFs (or pay vision costs) on any later run:

  <extraction dir>/submitted-resume.txt       resume pages (from the submitted resume PDF)
  <extraction dir>/submitted-coverletter.txt  cover-letter pages (found by CONTENT, any PDF)
  <extraction dir>/submitted-answers.txt      application Q&A (pasted application-answers.txt wins;
                                              else answer-classified PDF pages; screenshots are
                                              listed in the manifest for agent transcription)
  <extraction dir>/coverletter-diff.txt       sentence-level unified diff: the cover-letter
                                              baseline (normalized) vs the submitted letter,
                                              labelled by its real path. THE feedback signal.
  <extraction dir>/MANIFEST.txt               what was found, how pages were classified, what's missing

The extraction directory is "_JAIL Agent Work/Reconcile Agent/" as of 2026-08-06. Folders extracted
before that keep their results in a top-level "_extracted/" and are read there, never re-extracted —
this script prints the resolved path as "EXTRACTION_DIR: <path>" so callers never assume one.

The candidate's identity chrome (signature line, personal domains) is read from
PRIVATE__YOUR_FILES_GITIGNORED/04-TAILOR__YOUR_PRIVATE_INFO/cover-letter/config.json (signature_name, personal_domains) when it exists, so
template header/contact lines never pollute the diff. Without that config, generic contact-line
filters still apply.

Usage: .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/learning/extract_submission.py "<folder>" [--force]
Cached: exits immediately if the resolved extraction dir already has MANIFEST.txt (--force redoes it).
Needs pypdf (in the .venv). Only ever writes inside the job folder.
"""

import difflib
import json
import re
import sys
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    print("pypdf is not installed. Run: .venv/bin/pip install pypdf", file=sys.stderr)
    sys.exit(2)

SIGNOFFS = ("looking forward", "warmly,", "sincerely", "best,", "thank you for", "i'd love the chance")
RESUME_MARKERS = ("experience", "skills", "education", "summary", "professional")

# Where artifacts live inside a job folder is owned by ONE module, so the Python readers, the
# back-fill migration, and the agent prompts can't drift apart. Re-exported here because this
# file was the original home and other callers (and the tests) import these names from it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from job_folder_layout import (  # noqa: E402
    AGENT_WORK_DIRS,
    EXTRACTION_MANIFEST,
    VERSION_SUFFIX_RE,
    agent_work_dir,
    coverletter_baseline,
    coverletter_packet,
    extraction_dir_for_read,
    extraction_dir_for_write,
    find_agent_artifact,
    resume_base_comparison,
    work_dir_for_write,
)


def load_identity():
    """(signature_name, [personal domains]) from the cover-letter config, if set up."""
    cfg_path = Path(__file__).resolve().parents[3] / "PRIVATE__YOUR_FILES_GITIGNORED" / "04-TAILOR__YOUR_PRIVATE_INFO" / "cover-letter" / "config.json"
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            return cfg.get("signature_name") or None, [d for d in cfg.get("personal_domains", []) if d]
        except (OSError, ValueError):
            pass
    return None, []


SIGNATURE_NAME, PERSONAL_DOMAINS = load_identity()
_domain_alt = "".join("|" + re.escape(d) for d in PERSONAL_DOMAINS)
CONTACT_RE = re.compile(r"@|linkedin\.com" + _domain_alt + r"|\(\d{3}\)\s*\d{3}", re.I)


def classify_page(text):
    """-> 'coverletter' | 'answers' | 'resume' (order of checks matters)."""
    t = text.lower()
    head, tail = t[:500], t[-600:]
    if "dear " in head and (any(s in tail for s in SIGNOFFS) or "re:" in head):
        return "coverletter"
    if re.search(r"^re:", head, re.M) and any(s in tail for s in SIGNOFFS):
        return "coverletter"
    # answers: multiple question lines followed by prose
    q_lines = len(re.findall(r"^[^\n?]{15,140}\?\s*$", text, re.M))
    if q_lines >= 2:
        return "answers"
    if "application for" in head and q_lines >= 1:
        return "answers"
    hits = sum(1 for m in RESUME_MARKERS if m in t)
    if hits >= 2:
        return "resume"
    # single long question + long answer shape
    if q_lines == 1 and len(t.split()) > 80:
        return "answers"
    return "resume"


def normalize_for_diff(text, is_markdown=False):
    """Markdown/PDF-safe normalization -> one sentence per line."""
    if is_markdown:
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)   # links -> anchor text
        text = text.replace("**", "").replace("*", "")
    # drop header/contact/banner lines (letterhead template chrome, not letter content)
    kept = []
    for ln in text.splitlines():
        s = ln.strip()
        if CONTACT_RE.search(s) and len(s) < 140:
            continue
        if SIGNATURE_NAME and s == SIGNATURE_NAME:
            continue
        kept.append(ln)
    text = "\n".join(kept)
    # unify typography + PDF extraction artifacts (ligatures, bullets, stray spaces)
    pairs = [("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
             ("—", ", "), ("–", "-"), (" ", " "),
             ("ﬁ", "fi"), ("ﬂ", "fl"), ("ﬀ", "ff"), ("ﬃ", "ffi"), ("ﬄ", "ffl")]
    for a, b in pairs:
        text = text.replace(a, b)
    text = re.sub(r"[•‣▪]\s*", " ", text)
    text = re.sub(r"^[-*]\s+", " ", text, flags=re.M)
    text = re.sub(r"-\n(\w)", r"\1", text)          # de-hyphenate PDF line breaks
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)    # "MVP ." -> "MVP."
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if len(s.split()) >= 2]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    folder = Path(sys.argv[1]).expanduser()
    force = "--force" in sys.argv
    if not folder.is_dir():
        print(f"not a folder: {folder}", file=sys.stderr)
        return 2
    # Read-resolve first: a folder extracted before the lane split still holds its results in a
    # top-level "_extracted/". Skipping this check would re-extract every one of those and leave
    # two extraction directories per folder, free to diverge.
    cached = extraction_dir_for_read(folder)
    manifest_path = cached / EXTRACTION_MANIFEST
    if manifest_path.exists() and not force:
        # Announce the resolved directory before anything else. Readers (the reconcile agent)
        # take the path from HERE rather than hardcoding one, so a folder in any historical
        # shape is read from wherever its results actually are.
        print(f"EXTRACTION_DIR: {cached}")
        print(manifest_path.read_text(encoding="utf-8"))
        print("(cached — pass --force to re-extract)")
        return 0
    # Re-extraction rewrites in place when the results are already here; a fresh run writes to
    # the current shape.
    out = cached if manifest_path.exists() else extraction_dir_for_write(folder)
    out.mkdir(parents=True, exist_ok=True)
    print(f"EXTRACTION_DIR: {out}")

    manifest = [f"Extraction manifest for: {folder.name}", ""]
    resume_parts, letter_parts, answer_parts = [], [], []
    letter_by_pdf = {}  # pdf name -> [page texts]; the diff uses ONE copy, not concatenated duplicates

    pdfs = sorted(p for p in folder.glob("*.pdf"))
    for pdf in pdfs:
        name_l = pdf.name.lower()
        # skip the scraped job post / JD PDFs — they're inputs, not submissions
        if any(k in name_l for k in ("_jd_", "job description", "jobdescription")):
            manifest.append(f"SKIP (job description): {pdf.name}")
            continue
        try:
            reader = PdfReader(str(pdf))
        except Exception as e:
            manifest.append(f"ERROR reading {pdf.name}: {e}")
            continue
        kinds = []
        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if not text:
                kinds.append(f"p{i+1}:empty")
                continue
            kind = classify_page(text)
            # filename hints override weak page signals
            if "coverletter" in name_l.replace(" ", "").replace("-", ""):
                kind = "coverletter"
            if "job application for" in name_l:
                kind = "answers" if kind == "resume" else kind
            kinds.append(f"p{i+1}:{kind}")
            block = f"[{pdf.name} — page {i+1}]\n{text}\n"
            {"resume": resume_parts, "coverletter": letter_parts, "answers": answer_parts}[kind].append(block)
            if kind == "coverletter":
                letter_by_pdf.setdefault(pdf.name, []).append(text)
        manifest.append(f"{pdf.name}: {', '.join(kinds)}")

    # pasted answers file wins over PDF-extracted answers
    pasted = None
    for cand in ("application-answers.txt", "application answers.txt", "answers.txt"):
        p = folder / cand
        if p.exists():
            pasted = p
            break

    (out / "submitted-resume.txt").write_text("\n".join(resume_parts) or "(no resume pages found)", encoding="utf-8")
    (out / "submitted-coverletter.txt").write_text("\n".join(letter_parts) or "(no cover-letter pages found)", encoding="utf-8")
    if pasted:
        (out / "submitted-answers.txt").write_text(
            f"[verbatim from {pasted.name} — pasted by the candidate, preferred source]\n" + pasted.read_text(encoding="utf-8"),
            encoding="utf-8")
        manifest.append(f"ANSWERS: verbatim from pasted {pasted.name} (PDF answer pages ignored: {len(answer_parts)})")
    else:
        (out / "submitted-answers.txt").write_text("\n".join(answer_parts) or "(no answers found)", encoding="utf-8")
        manifest.append(f"ANSWERS: {len(answer_parts)} PDF page(s) classified as answers")

    # screenshots that may hold answers — agent transcribes ONCE if answers are missing/thin
    shots = [p.name for p in sorted(folder.glob("*.png")) + sorted(folder.glob("*.jpg")) + sorted(folder.glob("*.jpeg"))]
    if shots:
        manifest.append("SCREENSHOTS (transcribe once into submitted-answers.txt if they hold Q&A not already captured): " + ", ".join(shots))

    # cover-letter diff vs baseline — use ONE letter copy (prefer the dedicated CoverLetter PDF)
    baseline = coverletter_baseline(folder)
    if baseline and letter_by_pdf:
        pick = next((n for n in letter_by_pdf if "coverletter" in n.lower().replace(" ", "").replace("-", "")),
                    next(iter(letter_by_pdf)))
        manifest.append(f"COVERLETTER-DIFF source: {pick}")
        # Full path relative to the job folder. Under lanes the parent dir alone would
        # read as a bare "Cover Letter Agent/final.md"; this also reproduces the exact
        # "_cl_work/final.md" / "_JAIL Agent Work/final.md" labels older folders carry.
        base_label = str(baseline.relative_to(folder))
        base_sents = normalize_for_diff(baseline.read_text(encoding="utf-8"), is_markdown=True)
        sub_sents = normalize_for_diff("\n".join(letter_by_pdf[pick]))
        diff = list(difflib.unified_diff(base_sents, sub_sents, lineterm="",
                                         fromfile=f"baseline ({base_label})", tofile="submitted (PDF)", n=1))
        (out / "coverletter-diff.txt").write_text(
            "\n".join(diff) if diff else "(no differences — submitted letter matches the baseline)", encoding="utf-8")
        manifest.append(f"COVERLETTER-DIFF: {sum(1 for d in diff if d[:1] in '+-' and d[:3] not in ('+++','---'))} changed sentence(s)")
    elif letter_parts:
        manifest.append('COVERLETTER-DIFF: no baseline (no "_JAIL Agent Work/final.md" or legacy "_cl_work/final.md" — letter predates the cover-letter workflow); style observations only')
    else:
        manifest.append("COVERLETTER-DIFF: no cover letter found in any PDF")

    manifest_path.write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print("\n".join(manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
