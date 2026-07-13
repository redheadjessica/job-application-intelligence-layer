#!/usr/bin/env python3
"""Shared prep-reliability helpers used by both fetchers.

One place for: URL normalization + dedupe keys, collision-safe filenames,
thin/failed classification, the per-batch quarantine layout, manifest read/
write/merge, and the human-readable prep report. Both prep_job_urls.py
(requests) and prep_job_urls_playwright.py (render) call process_urls() with a
script-specific `fetch_one` callback so the dedupe / classify / quarantine /
manifest logic lives here, not duplicated.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from ats_fetchers import (
    ATS_HOST_KEYWORDS,
    UUID_RE,
    _greenhouse_ids,
    _linkedin_job_id,
)

# --------------------------------------------------------------------------- #
# Status vocabulary (kept stable so the manifest is a contract ranking can read)
# --------------------------------------------------------------------------- #
USABLE = "usable"
THIN = "thin"
FAILED = "failed"
DUPLICATE = "duplicate"
NEEDS_REVIEW = "needs-review"

# A job-text body shorter than this is quarantined as "thin". Tunable.
THIN_CHAR_THRESHOLD = 700

# Query params that are tracking/noise and safe to drop for the dedupe key.
# (utm_* is handled by prefix; these are exact-match.)
_TRACKING_PARAMS = {
    "gh_src", "gh_jid", "ref", "referrer", "source", "src", "trk", "trackingid",
    "lipi", "refid", "lici", "recommended", "spreadsheet", "fbclid", "gclid",
    "mc_cid", "mc_eid", "campaign", "medium",
}

# Signals a page is a login/apply shell, not the actual posting.
_SHELL_MARKERS = (
    "sign in", "log in to apply", "create an account", "please enable javascript",
    "enable javascript", "you need to enable", "verify you are human", "captcha",
)
# Signals real job content (any one is enough to look like a posting).
_CONTENT_MARKERS = (
    "responsib", "requirement", "qualificat", "what you", "about the role",
    "about the job", "you'll", "you will", "experience", "we're looking",
    "what we", "the role", "responsibilities",
)


# --------------------------------------------------------------------------- #
# Slug + filenames
# --------------------------------------------------------------------------- #
def slugify(text: str, max_len: int = 80) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len] or "job"


def first_line(title: str) -> str:
    return (title or "").split("|")[0].split(" - ")[0].strip()


def base_filename(company: str, title: str) -> str:
    return f"{slugify(company)}__{slugify(first_line(title))}.txt"


def _short_hash(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:6]


def source_token(url: str) -> str | None:
    """Return the ATS platform name (greenhouse/lever/ashby/linkedin/...) if the
    host is a known ATS — used as a friendly collision suffix. None otherwise."""
    host = urlparse(url).netloc.lower().replace("www.", "")
    parts = host.split(".")
    guess = parts[-2] if len(parts) >= 2 else host
    return guess if guess in ATS_HOST_KEYWORDS else None


def unique_filename(company: str, title: str, normalized_url: str,
                    taken: dict[str, str], url: str) -> str:
    """Collision-safe, deterministic filename. Base is `{company}__{title}.txt`.
    If that base is already taken by a DIFFERENT normalized URL, append a stable
    suffix: the ATS source token when available, else a short hash of the
    normalized URL. Re-fetching the SAME url yields the SAME name (retry-safe).
    `taken` maps already-used filename -> the normalized_url that owns it."""
    base = base_filename(company, title)
    if taken.get(base) in (None, normalized_url):
        return base
    suffix = source_token(url) or _short_hash(normalized_url)
    return f"{base[:-4]}-{suffix}.txt"


def failed_filename(url: str, normalized_url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "") or "unknown"
    return f"{slugify(host)}__failed-{_short_hash(normalized_url)}.txt"


# --------------------------------------------------------------------------- #
# URL normalization (conservative — only strip KNOWN noise; never merge unsure)
# --------------------------------------------------------------------------- #
def _lever_id(url: str):
    parts = [p for p in urlparse(url).path.split("/") if p]
    if not parts:
        return None, None
    org = parts[0]
    for p in parts[1:]:
        if UUID_RE.fullmatch(p):
            return org, p.lower()
    m = UUID_RE.search(url)
    return (org, m.group(0).lower()) if m else (org, None)


def ats_canonical_key(url: str) -> str | None:
    """A stable canonical id for a known ATS job, so two URL forms of the same
    posting collapse to one dedupe key. None if not a recognized ATS job."""
    host = urlparse(url).netloc.lower()
    try:
        if host.endswith("ashbyhq.com"):
            parts = [p for p in urlparse(url).path.split("/") if p]
            org = parts[0] if parts else None
            m = UUID_RE.search(url)
            if org and m:
                return f"ashby:{org.lower()}:{m.group(0).lower()}"
        if host.endswith("greenhouse.io"):
            board, jid = _greenhouse_ids(url)
            if board and jid:
                return f"greenhouse:{board.lower()}:{jid}"
        if "lever.co" in host:
            org, lid = _lever_id(url)
            if org and lid:
                return f"lever:{org.lower()}:{lid}"
        if "linkedin.com" in host:
            jid = _linkedin_job_id(url)
            if jid:
                return f"linkedin:{jid}"
    except Exception:
        return None
    return None


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k.startswith("utm_") or k in _TRACKING_PARAMS


def normalize_url(url: str) -> str:
    """Canonical dedupe key. Prefer a known-ATS job id; otherwise a conservative
    generic normalization (lowercase host, drop www/fragment/trailing-slash,
    strip known tracking params, sort the rest). Unknown params are KEPT — they
    might distinguish two real jobs."""
    url = (url or "").strip()
    key = ats_canonical_key(url)
    if key:
        return key
    p = urlparse(url)
    scheme = (p.scheme or "https").lower()
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    q = parse_qs(p.query, keep_blank_values=True)
    kept = [(k, v) for k, vals in q.items() if not _is_tracking(k) for v in vals]
    query = urlencode(sorted(kept))
    path = p.path.rstrip("/") or "/"
    return urlunparse((scheme, host, path, "", query, ""))


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def classify(body: str, *, is_ats: bool = False) -> tuple[str, str]:
    """Return (status, reason). USABLE / THIN / FAILED based on the extracted
    job-text body. ATS API results are trusted unless empty."""
    b = (body or "").strip()
    n = len(b)
    if n == 0:
        return FAILED, "empty body"
    low = b.lower()
    has_content = any(m in low for m in _CONTENT_MARKERS)
    is_shell = any(m in low for m in _SHELL_MARKERS)
    if is_ats:
        return (USABLE, "") if n > 0 else (FAILED, "empty body")
    if is_shell and not has_content:
        return THIN, "looks like a login/apply shell (no job content)"
    if n < THIN_CHAR_THRESHOLD:
        return THIN, f"short body ({n} chars, under {THIN_CHAR_THRESHOLD})"
    if not has_content and n < THIN_CHAR_THRESHOLD * 2:
        return THIN, "no clear responsibilities/requirements content"
    return USABLE, ""


# --------------------------------------------------------------------------- #
# Output text + quarantine stubs
# --------------------------------------------------------------------------- #
def build_output_text(url: str, title: str, company: str, body_text: str) -> str:
    return (
        f"URL: {url}\n"
        f"Page Title: {title}\n"
        f"Company: {company}\n\n"
        f"--- JOB TEXT START ---\n\n"
        f"{body_text}\n\n"
        f"--- JOB TEXT END ---\n"
    )


def thin_text(url: str, title: str, company: str, body_text: str, reason: str, ts: str) -> str:
    return (
        f"# QUARANTINED — THIN FETCH (needs your review)\n"
        f"# Reason: {reason}\n"
        f"# Fetched: {ts}\n"
        f"# What to do: open this, confirm it's the real job post. If it's incomplete,\n"
        f"#   paste the full job text below the marker, then re-run prep (it will pick it up),\n"
        f"#   OR move this file into 'All Job Posts (full text)/' if it's actually fine.\n\n"
        + build_output_text(url, title, company, body_text)
    )


def failed_text(url: str, error: str, ts: str) -> str:
    return (
        f"# FAILED FETCH (no usable content)\n"
        f"# URL: {url}\n"
        f"# Error: {error}\n"
        f"# Fetched: {ts}\n"
        f"# What to do: re-run prep to retry this URL, or paste the full job text below\n"
        f"#   the marker and move this file into 'All Job Posts (full text)/'.\n\n"
        f"--- JOB TEXT START ---\n\n\n--- JOB TEXT END ---\n"
    )


# --------------------------------------------------------------------------- #
# Batch layout + manifest + report
# --------------------------------------------------------------------------- #
def batch_dirs(source_dir) -> dict:
    """Given the source folder (".../3 - Source Material/All Job Posts (full text)"),
    derive the sibling quarantine dirs and the batch's prep-report dir."""
    src = Path(source_dir).resolve()
    sm = src.parent            # "3 - Source Material"
    batch = sm.parent          # batch root (__READY TO REVIEW/MM-DD-YY)
    return {
        "batch": batch,
        "source": src,
        "needs_review": sm / "Needs Review",
        "failed": sm / "Failed",
        "report": batch / "0 - Prep Report",
    }


def ensure_dirs(dirs: dict) -> None:
    for k in ("source", "needs_review", "failed", "report"):
        dirs[k].mkdir(parents=True, exist_ok=True)


def _rel(path: Path, batch: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(batch.resolve()))
    except Exception:
        return str(path)


def new_manifest(batch: str) -> dict:
    return {"schema_version": 1, "batch": batch, "fetched_at": None,
            "input_count": 0, "counts": {}, "entries": []}


def load_manifest(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def save_manifest(path: Path, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _counts(entries: list[dict]) -> dict:
    c = {USABLE: 0, THIN: 0, FAILED: 0, DUPLICATE: 0, NEEDS_REVIEW: 0}
    for e in entries:
        c[e["status"]] = c.get(e["status"], 0) + 1
    return c


def write_report(path: Path, manifest: dict) -> None:
    e = manifest["entries"]
    c = manifest["counts"]
    usable = [x for x in e if x["status"] == USABLE]
    thin = [x for x in e if x["status"] == THIN]
    failed = [x for x in e if x["status"] == FAILED]
    dups = [x for x in e if x["status"] == DUPLICATE]
    possible = [x for x in usable if x.get("possible_duplicate_group")]
    safe = "Yes — usable posts are ready to rank." if usable else "No usable posts yet."

    lines = [f"# Prep Report — {manifest['batch']}", ""]
    lines.append(f"Prep finished. I found {manifest['input_count']} URL(s):")
    lines.append(f"- ✅ {c.get(USABLE,0)} usable job post(s)  → \"3 - Source Material/All Job Posts (full text)/\"")
    lines.append(f"- ♻️ {c.get(DUPLICATE,0)} duplicate(s) skipped")
    lines.append(f"- ⚠️ {c.get(THIN,0)} thin post(s) — needs review  → \"3 - Source Material/Needs Review/\"")
    lines.append(f"- ❌ {c.get(FAILED,0)} failed fetch(es)  → \"3 - Source Material/Failed/\"")
    lines.append(f"- 👀 {len(possible)} possible same company/title duplicate(s) — review")
    lines += ["", f"**Safe to rank now?** {safe}", ""]
    lines.append("Usable posts are ready for ranking. Please review the thin/failed items before "
                 "relying on them (open them, paste the real job text if needed, then re-run prep).")
    lines += ["", "## Details"]
    if possible:
        lines.append("**Possible duplicates (kept both — review):**")
        for x in possible:
            lines.append(f"- {x.get('company','?')} — {x.get('title','?')}  ({x['original_url']})")
    if thin:
        lines.append("**Thin (in Needs Review/):**")
        for x in thin:
            lines.append(f"- {Path(x.get('quarantine_path','')).name} — {x.get('notes','')}  ({x['original_url']})")
    if failed:
        lines.append("**Failed (in Failed/):**")
        for x in failed:
            lines.append(f"- {x['original_url']} — {x.get('error','error')}")
    if dups:
        lines.append("**Duplicates skipped:**")
        for x in dups:
            lines.append(f"- {x['original_url']}  (same as {x.get('duplicate_of','')})")
    lines.append("")
    lines.append("Next: rank the usable posts. For thin/failed ones, paste the real text or re-run prep to retry.")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _remove_if_exists(rel_path: str, batch: Path) -> None:
    if not rel_path:
        return
    fp = (batch / rel_path)
    try:
        if fp.exists():
            fp.unlink()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Orchestrator — both scripts call this with their own fetch_one()
# --------------------------------------------------------------------------- #
def process_urls(urls: list[str], source_dir, fetch_one, *, force: bool = False) -> dict:
    """fetch_one(url) -> dict: {ok: bool, title, company, body, method, error}.
    Manifest-aware: a plain re-run skips already-usable URLs and retries
    thin/failed ones (set force=True to refetch everything)."""
    dirs = batch_dirs(source_dir)
    ensure_dirs(dirs)
    batch_root = dirs["batch"]
    mpath = dirs["report"] / "prep-manifest.json"
    manifest = load_manifest(mpath) or new_manifest(batch_root.name)
    prev_by_norm = {e["normalized_url"]: e for e in manifest.get("entries", [])}

    # Rebuild the "taken filename -> owning normalized_url" map from prior entries.
    taken: dict[str, str] = {}
    for e in manifest.get("entries", []):
        rel = e.get("output_path") or e.get("quarantine_path")
        if rel:
            taken[Path(rel).name] = e["normalized_url"]

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries: list[dict] = []
    seen: dict[str, str] = {}   # normalized_url -> original_url (first this run)

    def base_entry(url, norm, **kw):
        d = {"original_url": url, "normalized_url": norm, "status": None, "method": None,
             "company": None, "title": None, "char_count": None, "output_path": None,
             "quarantine_path": None, "duplicate_of": None, "duplicate_group": None,
             "possible_duplicate_group": None, "notes": "", "error": None, "fetched_at": ts}
        d.update(kw)
        return d

    for raw in urls:
        url = raw.strip()
        if not url or url.startswith("#"):
            continue
        norm = normalize_url(url)

        if norm in seen:
            entries.append(base_entry(url, norm, status=DUPLICATE, duplicate_of=seen[norm],
                                      notes="exact/normalized duplicate of an earlier URL this run"))
            continue
        seen[norm] = url

        prev = prev_by_norm.get(norm)
        if prev and prev.get("status") == USABLE and not force:
            carried = dict(prev)
            carried["notes"] = (prev.get("notes") or "").strip() or "carried forward (already usable)"
            entries.append(carried)
            continue

        # Retrying this URL: remove any prior file so we never orphan/duplicate.
        if prev:
            _remove_if_exists(prev.get("output_path"), batch_root)
            _remove_if_exists(prev.get("quarantine_path"), batch_root)
            for fn, owner in list(taken.items()):
                if owner == norm:
                    taken.pop(fn, None)

        res = fetch_one(url) or {}
        if not res.get("ok"):
            fn = failed_filename(url, norm)
            out = dirs["failed"] / fn
            out.write_text(failed_text(url, res.get("error") or "fetch failed", ts), encoding="utf-8")
            entries.append(base_entry(url, norm, status=FAILED, method=res.get("method"),
                                      error=res.get("error") or "fetch failed",
                                      quarantine_path=_rel(out, batch_root)))
            continue

        title = (res.get("title") or "Unknown Title").strip()
        company = (res.get("company") or "Unknown").strip()
        body = res.get("body") or ""
        method = res.get("method")
        status, reason = classify(body, is_ats=(method == "ats"))

        fn = unique_filename(company, title, norm, taken, url)
        taken[fn] = norm
        if status == USABLE:
            out = dirs["source"] / fn
            out.write_text(build_output_text(url, title, company, body), encoding="utf-8")
            entries.append(base_entry(url, norm, status=USABLE, method=method, company=company,
                                      title=title, char_count=len(body), output_path=_rel(out, batch_root)))
        else:  # THIN
            out = dirs["needs_review"] / fn
            out.write_text(thin_text(url, title, company, body, reason, ts), encoding="utf-8")
            entries.append(base_entry(url, norm, status=THIN, method=method, company=company,
                                      title=title, char_count=len(body), notes=reason,
                                      quarantine_path=_rel(out, batch_root)))

    # Soft-flag possible same company/title duplicates among usable posts (keep both).
    groups: dict[tuple, list[dict]] = {}
    for e in entries:
        if e["status"] == USABLE and e.get("company") and e.get("title"):
            groups.setdefault((e["company"].lower(), first_line(e["title"]).lower()), []).append(e)
    gid = 0
    for key, members in groups.items():
        if len(members) > 1:
            gid += 1
            for m in members:
                m["possible_duplicate_group"] = f"g{gid}"
                m["notes"] = (m["notes"] + "; possible same company/title duplicate — review").strip("; ")

    manifest["entries"] = entries
    manifest["input_count"] = sum(1 for u in urls if u.strip() and not u.strip().startswith("#"))
    manifest["counts"] = _counts(entries)
    manifest["fetched_at"] = ts
    save_manifest(mpath, manifest)
    write_report(dirs["report"] / "prep-report.md", manifest)
    _print_summary(manifest, dirs)
    return manifest


def _print_summary(manifest: dict, dirs: dict) -> None:
    c = manifest["counts"]
    print("")
    print(f"Prep finished — {manifest['input_count']} URL(s):")
    print(f"  usable:   {c.get(USABLE,0)}   (ready to rank)")
    print(f"  thin:     {c.get(THIN,0)}   (in 'Needs Review/')")
    print(f"  failed:   {c.get(FAILED,0)}   (in 'Failed/')")
    print(f"  dupes:    {c.get(DUPLICATE,0)}   (skipped)")
    possible = sum(1 for e in manifest["entries"] if e.get("possible_duplicate_group"))
    if possible:
        print(f"  possible same company/title dupes: {possible} (kept both — review)")
    print(f"Report:   {dirs['report'] / 'prep-report.md'}")
    print(f"Usable:   {dirs['source']}")
