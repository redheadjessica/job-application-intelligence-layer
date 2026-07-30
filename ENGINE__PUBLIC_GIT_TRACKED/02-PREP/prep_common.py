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
from html import unescape as html_unescape
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from ats_fetchers import (
    ATS_HOST_KEYWORDS,
    UUID_RE,
    _greenhouse_ids,
    _linkedin_job_id,
    _prettify_slug,
    parse_office_cadence,
    question_provides_employer_comp,
    question_provides_working_location,
    recover_embedded_greenhouse,
)

# --------------------------------------------------------------------------- #
# Per-field completeness vocabulary (comp + working-location gate before ranking)
# --------------------------------------------------------------------------- #
FOUND = "found"
NOT_POSTED = "not_posted"
CAPTURE_FAILED = "capture_failed"
CONFLICTING = "conflicting"
# Hard fields that gate ranking quality (never a reason to quarantine, though).
HARD_FIELDS = ("compensation", "working_location")

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
# Double-quote-like characters that a verbatim question label sometimes carries
# on one or both ends. We wrap the label in our own quotes when emitting it, so a
# stray one doubles up (e.g. `…delivery?""`). Strip only these wrapping quotes;
# apostrophes and quotes *inside* the label are left untouched.
_WRAP_QUOTES = "\"“”„‟"


def _strip_wrapping_quotes(text: str) -> str:
    """Trim stray leading/trailing double-quote characters so a verbatim label
    doesn't render a doubled quote when we wrap it in our own."""
    return (text or "").strip().strip(_WRAP_QUOTES).strip()


def slugify(text: str, max_len: int = 80) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len] or "job"


def first_line(title: str) -> str:
    return (title or "").split("|")[0].split(" - ")[0].strip()


def base_filename(company: str, title: str) -> str:
    return f"{slugify(company)}__{slugify(first_line(title))}.txt"


# --------------------------------------------------------------------------- #
# Captured-identity normalization — `company-name__job-title.txt` (spec 2026-07-29)
#
# Every fetch path (ATS API / requests / playwright / JSON-LD / embedded-GH recovery)
# funnels its (company, title) pair through `normalize_capture_identity` at the ONE choke
# point in `process_urls`, so a posting gets the same filename and the same
# `Company:`/`Role:` header regardless of which method won the race. That single
# insertion point is what makes it idempotent per URL: re-normalizing an already-clean
# identity is a no-op.
#
# The regression this fixes: careers.airbnb.com produced BOTH
# `careers-at-airbnb__product-manager-incubations.txt` (playwright: `best_company_from_title`
# accepted "Careers at Airbnb" as the company) AND
# `product-manager-incubations__product-manager-incubations.txt` (requests: `detect_company`
# rejected the career-y segment and fell through to the ROLE segment). The only correct name
# is `airbnb__product-manager-incubations.txt`.
# --------------------------------------------------------------------------- #

# "Careers at X" / "Jobs at X" prefix and "X Careers" / "X Jobs" suffix wrappers.
_CO_WRAPPER_PREFIX_RE = re.compile(r"^(?:careers?|jobs?)\s+at\s+", re.I)
_CO_WRAPPER_SUFFIX_RE = re.compile(r"[\s|·]+(?:careers?|jobs?)$", re.I)
# Any residual site-branding word means the value is chrome, not an employer name.
_CAREERY_RE = re.compile(r"\b(careers?|jobs?)\b", re.I)
# Separator between a real title and a trailing site-branding suffix.
_BRAND_SEP = r"\s*[|\-–—·]\s*"
# "<Role> - Careers at <Co>" / "<Role> — Jobs at <Co>"
_TITLE_SUFFIX_AT_RE = re.compile(
    rf"{_BRAND_SEP}(?:careers?|jobs?)\s+at\s+(?P<co>[^|\-–—·]+?)\s*$", re.I)
# "<Role> | <Co> Careers" / "<Role> - <Co> Jobs"
_TITLE_SUFFIX_CO_RE = re.compile(
    rf"{_BRAND_SEP}(?P<co>[^|\-–—·]+?)\s+(?:careers?|jobs?)\s*$", re.I)
# "<Role> | Careers" / "<Role> - Jobs" (branding with no employer name in it)
_TITLE_SUFFIX_BARE_RE = re.compile(rf"{_BRAND_SEP}(?:careers?|jobs?)\s*$", re.I)
# Job-board hosts that are never the employer (the ATS hosts are handled separately).
_BOARD_HOSTS = {
    "linkedin", "indeed", "glassdoor", "ziprecruiter", "wellfound", "angellist",
    "builtin", "otta", "dice", "monster", "simplyhired", "google", "jobs",
}
# Domain labels that are site structure, never a company name.
_DOMAIN_CHROME = {
    "careers", "career", "jobs", "job", "www", "apply", "boards", "board", "work",
    "hire", "hiring", "talent", "recruiting", "join", "my", "app", "web",
}
_PSEUDO_TLDS = {"co", "com", "org", "net", "gov", "edu", "ac"}


def _clean_company_wrappers(name: str) -> str:
    """Strip `Careers at X` / `Jobs at X` / `X Careers` / `X Jobs` wrappers (case-
    insensitive, iteratively) and any stray separator punctuation left behind."""
    s = re.sub(r"\s+", " ", str(name or "").strip())
    for _ in range(4):
        before = s
        s = _CO_WRAPPER_PREFIX_RE.sub("", s)
        s = _CO_WRAPPER_SUFFIX_RE.sub("", s)
        s = s.strip(" \t|·:,-–—")
        if s == before:
            break
    s = re.sub(r"\s+", " ", s).strip()
    # A name we DERIVED by stripping a wrapper often comes out of lowercase page chrome
    # ("careers at airbnb" -> "airbnb"); title-case it so the header and the filename agree
    # with every other route. A company that arrived already cased is left alone.
    if s and s != str(name or "").strip() and not any(ch.isupper() for ch in s):
        s = _prettify_slug(s)
    return s


def _strip_title_branding(title: str) -> tuple[str, str | None]:
    """Remove site-branding suffixes from a page/job title. Returns
    (clean_title, employer_name_recovered_from_the_suffix_or_None) — the suffix often
    NAMES the employer ("- Careers at Airbnb"), which is the best company signal a
    scraped page offers."""
    s = re.sub(r"\s+", " ", str(title or "").strip())
    wrapper_co = None
    for _ in range(3):
        before = s
        for rx in (_TITLE_SUFFIX_AT_RE, _TITLE_SUFFIX_CO_RE):
            m = rx.search(s)
            if m and m.start() > 0:
                co = _clean_company_wrappers(m.group("co"))
                if co and not _CAREERY_RE.search(co):
                    wrapper_co = wrapper_co or co
                s = s[:m.start()].strip(" \t|·:,-–—")
                break
        else:
            m = _TITLE_SUFFIX_BARE_RE.search(s)
            if m and m.start() > 0:
                s = s[:m.start()].strip(" \t|·:,-–—")
        if s == before:
            break
    return re.sub(r"\s+", " ", s).strip(), wrapper_co


def _company_from_domain(url: str | None) -> str | None:
    """Employer name derived from the URL host (`careers.airbnb.com` -> `Airbnb`). Returns
    None for ATS hosts and job boards, whose host names the platform, not the employer."""
    host = urlparse(url or "").netloc.lower().replace("www.", "")
    labels = [p for p in host.split(".") if p]
    if len(labels) < 2:
        return None
    idx = len(labels) - 2
    if labels[idx] in _PSEUDO_TLDS and len(labels) >= 3:  # example.co.uk
        idx -= 1
    label = labels[idx]
    if label in _DOMAIN_CHROME:
        return None
    if label in ATS_HOST_KEYWORDS or label in _BOARD_HOSTS:
        # A big-company domain can be BOTH a job board and its own employer careers site
        # (google.com/search/jobs vs google.com/about/careers/...). On an explicit `/careers`
        # path the host does name the employer — without this, a careers-site posting whose
        # title is also its company had no alternative name at all, so the ROLE stayed in the
        # company slot and the filename doubled it (`<role>__<role>.txt`).
        if not re.search(r"/careers(?:/|$)", urlparse(url or "").path, re.I):
            return None
    return _prettify_slug(label)


def _identity_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


# --------------------------------------------------------------------------- #
# "Never company-as-role" — the guard symmetric to never-role-as-company.
#
# The regression: a JS-rendered careers site (metacareers.com) whose <title>/og:title is
# pure site branding produced `Company: Meta Careers` / `Role: Meta Careers` and the
# filename `meta-careers__meta-careers.txt`. Cleaning the COMPANY was not enough — the
# role was still branding. A title that is site chrome must be RECOVERED from the page
# (JSON-LD title -> first <h1> -> first non-navigation heading in the extracted body),
# and if recovery fails the title is marked a CAPTURE FAILURE (field_status `title`
# -> capture_failed) so the completeness gate and the prep report say so loudly, rather
# than a branding string being minted into a filename as if it were a job title.
# --------------------------------------------------------------------------- #

# "Careers at X" / "Jobs | X" — a branding wrapper occupying the WHOLE string.
_BRAND_ONLY_PREFIX_RE = re.compile(rf"^(?:careers?|jobs?)(?:\s+at\s+|{_BRAND_SEP})", re.I)
# Words that only ever appear in site navigation / page chrome, never alone in a job
# title. A line whose every word is in this set (plus the employer's own name) is nav.
_NAV_WORDS = {
    "a", "about", "accessibility", "alerts", "all", "an", "and", "apply", "at", "back",
    "benefits", "blog", "blogs", "board", "career", "careers", "content", "contact",
    "cookie", "cookies", "culture", "current", "diversity", "employees", "events",
    "faq", "faqs", "for", "found", "help", "home", "hiring", "in", "internships",
    "investors", "job", "jobs", "join", "language", "life", "listings", "locations",
    "location", "log", "login", "logout", "main", "menu", "more", "news", "now", "of",
    "offices", "open", "openings", "or", "our", "out", "overview", "people", "podcast",
    "podcasts", "policy", "positions", "press", "privacy", "profile", "program",
    "programs", "resources", "results", "roles", "saved", "search", "sign", "skip",
    "students", "team", "teams", "terms", "the", "to", "up", "us", "view", "we",
    "work", "working",
}


# Generic ATS/careers PAGE titles that name the page, not the job. Matched exactly (after
# lowercasing + punctuation strip) so a real title is never caught by them.
_GENERIC_PAGE_TITLES = {
    "job details", "job detail", "details", "job description", "job posting", "job post",
    "job opening", "job openings", "position details", "position description",
    "opportunity details", "open positions", "open roles", "current openings",
    "job search", "search jobs", "apply now", "view job", "job", "jobs", "careers",
}


def _is_branding_only(text: str) -> bool:
    """True when a string is a careers-site branding label rather than a job title —
    "Meta Careers", "Careers at Acme", "Jobs — Acme", bare "Careers"/"Jobs".
    Deliberately narrow: only strings of at most 3 words qualify, so a real title that
    happens to contain the word "Careers" ("PM, Careers Platform Experience") is safe."""
    s = re.sub(r"\s+", " ", str(text or "").strip())
    if not s:
        return True
    if re.sub(r"\s+", " ", re.sub(r"[^a-z ]+", " ", s.lower())).strip() in _GENERIC_PAGE_TITLES:
        return True
    if len(s.split(" ")) > 3:
        return False
    return bool(_BRAND_ONLY_PREFIX_RE.match(s) or _CO_WRAPPER_SUFFIX_RE.search(s))


def _title_is_branding(title: str) -> bool:
    """The title carries no role information at all: missing, or pure site branding.
    This is the DEFINITE failure — worth a full page rescan to recover a real title."""
    s = str(title or "").strip()
    return (not s) or s == "Unknown Title" or _is_branding_only(s)


def _title_is_invalid(title: str, company: str) -> bool:
    """Branding, or the same slug as the company (company-as-role). A plain collision is
    ambiguous — it can equally mean the COMPANY is wrong — so callers distinguish it from
    `_title_is_branding` and never rewrite such a title from loose page text."""
    if _title_is_branding(title):
        return True
    k = _identity_key(title)
    return bool(k) and k == _identity_key(company)


def _headings_from_html(html: str | None) -> list[str]:
    """Heading text from a page's markup, <h1>s before <h2>s, tags stripped. A regex
    (not a parser) keeps prep_common dependency-free — this reads only heading text."""
    out: list[str] = []
    # Comments are markup, not content — and a comment mentioning a tag would otherwise
    # open a match that runs on until the real closing tag.
    src = re.sub(r"<!--.*?-->", " ", str(html or ""), flags=re.S)
    for level in ("h1", "h2"):
        for m in re.finditer(rf"<{level}\b[^>]*>(.*?)</{level}>", src, re.I | re.S):
            txt = re.sub(r"<[^>]+>", " ", m.group(1))
            txt = re.sub(r"\s+", " ", html_unescape(txt)).strip()
            if txt:
                out.append(txt)
    return out


# Job-description SECTION headers. These are the most likely wrong answer when scanning
# body text for a title, so they are rejected outright — a flagged capture failure beats a
# capture whose `Role:` line says "About the role".
_SECTION_HEADERS = {
    "about the role", "about the job", "about this role", "about this job", "about us",
    "about the team", "about the company", "the role", "the opportunity", "job description",
    "role description", "position summary", "overview", "summary", "responsibilities",
    "key responsibilities", "what you'll do", "what you will do", "what youll do",
    "qualifications", "minimum qualifications", "preferred qualifications", "requirements",
    "who you are", "what we're looking for", "what we are looking for", "nice to have",
    "benefits", "perks", "compensation", "salary", "pay transparency", "how to apply",
    "equal opportunity employer", "our mission", "why join us", "your impact",
}


def _first_content_heading(body: str | None, names: list[str]) -> str | None:
    """The first line of extracted body text that reads as a job title rather than
    navigation chrome or a JD section header. On the metacareers capture the body opens
    with "Skip to main content / Jobs / Teams / Career Programs / Working at Meta / Blog /
    Podcasts / Jobs" and then the real title, "Product Manager, Central Product"."""
    # The employer's own name(s) count as nav vocabulary only IN COMBINATION with a real nav
    # word ("Working at <Co>"). They can't stand alone as the test: when the company slot
    # holds the ROLE text, its words would otherwise mask the real title line.
    own = set()
    for name in names:
        own |= {w for w in re.split(r"[^a-z0-9]+", str(name or "").lower()) if w}
    nav = _NAV_WORDS | own
    for raw in str(body or "").splitlines()[:60]:
        ln = re.sub(r"\s+", " ", raw).strip(" \t|·:-–—")
        if not (6 <= len(ln) <= 120) or ln.endswith("."):  # a title is not a sentence
            continue
        if re.sub(r"[^a-z' ]+", "", ln.lower()).strip() in _SECTION_HEADERS:
            continue
        # Run-together case ("linkCopy link", "emailEmail a friend") is icon/label markup
        # collapsed by text extraction, never a real job title.
        if re.search(r"[a-z][A-Z]", ln):
            continue
        words = [w for w in re.split(r"[^A-Za-z0-9'&]+", ln) if w]
        low = [w.lower() for w in words]
        if len(words) < 2:
            continue
        if all(w in nav for w in low) and any(w in _NAV_WORDS for w in low):
            continue
        # Branding lines are skipped, but a line that merely MATCHES the "company" is kept:
        # when the title is branding, a company slot holding the same string as the body's
        # first content line is evidence the ROLE text landed in the company field, and the
        # role-as-company guard downstream is what repairs that.
        if _title_is_branding(ln):
            continue
        return ln
    return None


def _recover_title(jsonld: dict, html: str | None, body: str | None,
                   names: list[str], *, scan_body: bool = True) -> str | None:
    """Recover a real job title for a capture whose scraped title was branding.
    In order: JSON-LD `title`, the page's first heading, the first non-navigation
    heading line of the extracted body text. Returns None rather than inventing one.

    `names` is every name this employer is known by here (the cleaned company plus any
    domain-derived form) — a heading made only of nav words plus one of those names
    ("Working at Meta") is chrome, not a title.

    `scan_body=False` restricts recovery to the two HIGH-CONFIDENCE structured sources.
    Used when the title merely COLLIDES with the company: that can equally mean the company
    is the wrong one, and a loose body line is not good enough evidence to overwrite a
    title that may well be correct."""
    names = [n for n in names if str(n or "").strip()]
    candidates: list[str] = [str((jsonld or {}).get("title") or "")]
    candidates += _headings_from_html(html)
    heading = _first_content_heading(body, names) if scan_body else None
    if heading:
        candidates.append(heading)
    for cand in candidates:
        c = re.sub(r"\s+", " ", str(cand or "").strip())
        if not c:
            continue
        clean, _ = _strip_title_branding(c)
        clean = clean.strip()
        if clean and not _title_is_branding(clean):
            return clean
    return None


def _strip_trailing_company_echo(title: str, company: str) -> str:
    """Drop a trailing ` - <Company>` / ` | <Company>` echo from a title."""
    if not company or not title:
        return title
    m = re.search(rf"{_BRAND_SEP}{re.escape(company)}\s*$", title, re.I)
    if m and m.start() > 0:
        return title[:m.start()].strip(" \t|·:,-–—")
    return title


def normalize_capture_identity(company: str | None, title: str | None, url: str | None = None,
                               jsonld: dict | None = None, html: str | None = None,
                               body: str | None = None) -> tuple[str, str]:
    """Canonical (company, title) for a captured job post — the single normalizer behind
    the `company-name__job-title.txt` filename and the `Company:`/`Role:` header lines.

    Order of operations:
      1. Prefer structured JSON-LD identity (`hiringOrganization.name` / `title`).
      2. Strip site-branding suffixes from the title, remembering any employer name the
         suffix carried ("- Careers at Airbnb" -> Airbnb).
      3. Strip `Careers at X` / `X Jobs` wrappers from the company.
      4. If the company is empty or still career-y, use the suffix-derived name, else a
         domain-derived one.
      5. NEVER role-as-company: if the cleaned company equals (or contains / is contained
         by) the cleaned title, replace it with the suffix- or domain-derived name — but
         only when such an alternative actually exists (conservative: never invent one).
      6. NEVER company-as-role (symmetric guard): if the cleaned title is site branding
         ("Meta Careers", "Careers at X") or slugs to the same value as the company,
         RECOVER it from JSON-LD `title`, then the page's first heading, then the first
         non-navigation heading line of the extracted body. If nothing is recoverable the
         title becomes "Unknown Title", which `assess_completeness` records as
         `title: capture_failed` — a loud flag, never an invented or branding filename.

    Idempotent: an already-clean pair passes through unchanged.
    """
    jsonld = jsonld if isinstance(jsonld, dict) else {}
    raw_company = str(company or "").strip()
    raw_title = str(title or "").strip()
    j_co = str(jsonld.get("hiring_organization") or "").strip()
    j_title = str(jsonld.get("title") or "").strip()
    if j_co:
        raw_company = j_co
    if j_title:
        raw_title = j_title

    clean_title, wrapper_co = _strip_title_branding(raw_title)
    clean_company = _clean_company_wrappers(raw_company)
    domain_co = _company_from_domain(url)

    if not clean_company or _CAREERY_RE.search(clean_company):
        clean_company = wrapper_co or domain_co or clean_company
    clean_title = _strip_trailing_company_echo(clean_title, clean_company)

    # NEVER company-as-role. Attempted BEFORE the role-as-company swap below: when the two
    # values collide, recovering a real title from the page tells us which of the pair was
    # actually broken, so a good company name isn't thrown away to fix a bad title.
    names = [n for n in (clean_company, domain_co, wrapper_co) if n]
    if _title_is_invalid(clean_title, clean_company):
        recovered = _recover_title(jsonld, html, body, names,
                                   scan_body=_title_is_branding(clean_title))
        if recovered:
            clean_title = recovered

    # NEVER role-as-company. A company that is merely a SUBSTRING of a longer title is not
    # role-as-company: "Director, Product Management, ClassPass Consumer" legitimately names
    # its employer, and swapping in a domain-derived parent-company name there replaced a
    # correct, ATS-authoritative employer name with one the user wouldn't recognize. Require
    # the company to account for most of the title before treating it as the role.
    ck, tk = _identity_key(clean_company), _identity_key(clean_title)
    substantial = bool(ck) and bool(tk) and min(len(ck), len(tk)) >= 0.5 * max(len(ck), len(tk))
    if ck and tk and (ck == tk or (substantial and (ck in tk or tk in ck))):
        for alt in (wrapper_co, domain_co):
            if alt and _identity_key(alt) != tk:
                clean_company = alt
                break

    # Still branding: fail loudly rather than mint a filename out of site chrome.
    # "Unknown Title" is what assess_completeness reads as capture_failed. An UNRESOLVED
    # collision is deliberately NOT failed here — the title is probably the real role and
    # the company is the duplicated half, so keeping the role text loses less.
    if _title_is_branding(clean_title):
        clean_title = ""

    return (clean_company or "Unknown", clean_title or "Unknown Title")


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
    job-text body. ATS API results are trusted unless empty.

    BUG FIX (2026-07-16): the content-marker check used to only apply when the body was
    short (< THIN_CHAR_THRESHOLD * 2). A long body with ZERO job-posting content markers —
    e.g. a JS-rendered SPA whose raw HTML is mostly theme/config JSON, not the rendered job
    text — sailed through as USABLE purely because it was long. This is exactly how a
    488KB Microsoft careers-site boilerplate capture got scored as a real job (it wasn't).
    The has_content check now applies unconditionally: length alone never substitutes for
    actual job-posting content."""
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
    if not has_content:
        return THIN, (f"no job-posting content markers found (responsibilities/qualifications/"
                       f"about the role/etc.) despite {n} chars — likely boilerplate, theme "
                       f"config, or nav chrome rather than the actual posting text")
    return USABLE, ""


# --------------------------------------------------------------------------- #
# Completeness gate (compensation + working location) — runs BEFORE ranking
# --------------------------------------------------------------------------- #
def _norm_val(v) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip().lower())


def _distinct(values) -> list:
    seen, out = set(), []
    for v in values:
        if not v:
            continue
        k = _norm_val(v)
        if k and k not in seen:
            seen.add(k)
            out.append(str(v).strip())
    return out


# A plain HTML scrape (requests or a rendered page with no JSON-LD JobPosting) is
# NOT a structured source: a field missing from it is "could not verify"
# (capture_failed), never "not posted", because the real ATS API or a render
# routinely surfaces fields a plain scrape misses. Only a structured source (an
# ATS API, or a JSON-LD JobPosting) can testify that a field is genuinely absent.
_GENERIC_SOURCES = {"requests/html", "playwright/html"}


def _source_is_structured(meta: dict) -> bool:
    """True when a STRUCTURED source (ATS API or JSON-LD JobPosting) was
    successfully consulted for this posting. A genuinely-absent field is only
    trustworthy as `not_posted` from such a source; a bare generic HTML scrape
    yields `capture_failed` instead. An explicit meta['structured_source'] flag
    wins; otherwise anything not tagged as a generic HTML source is treated as
    structured (covers the ATS result dicts, which name themselves e.g.
    'greenhouse-boards-api')."""
    flag = meta.get("structured_source")
    if flag is not None:
        return bool(flag)
    return (meta.get("source") or "").strip().lower() not in _GENERIC_SOURCES


# --------------------------------------------------------------------------- #
# Prose fallback — the completeness verdict must match what the vetting scorer can
# actually read. The scorer reads the job-description BODY, so before we call a
# field capture_failed we scan that same prose: employers routinely write the pay
# range and the location into the JD text even when no structured field carries it.
# --------------------------------------------------------------------------- #

# A monetary amount: a comma-thousands number (240,000), a K-scaled number (180K),
# or a plain 4-7 digit number (240000). Plain small integers like "20" never match,
# so "10-20 people" can't be read as pay; the plain-digit form additionally requires
# a currency marker at match time (below) so ids/years don't false-positive.
_CUR = r"USD|US\$|CAD|C\$|A\$|AUD|EUR|GBP|\$|£|€"
_AMT = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{2,3}(?:\.\d+)?\s?[kK]|\d{4,7}(?:\.\d{2})?"
_PAY_RANGE_RE = re.compile(
    rf"(?P<cur1>{_CUR})?\s?"
    rf"(?P<lo>{_AMT})"
    rf"\s?(?:-|–|—|to|through)\s?"
    rf"(?P<cur2>{_CUR})?\s?"
    rf"(?P<hi>{_AMT})",
    re.I,
)
# BASE-salary keywords only. "ote" and "total comp" were removed (2026-07-29): a
# variable-pay figure is NOT base salary, and letting those keywords qualify a range meant
# an OTE number could become the captured comp value and flow into the Comp Range envelope.
# Bonus/commission/OTE/equity stay separate (they're preserved in the archival block and in
# `mine_benefits_equity`), never merged into base.
_SALARY_KEYWORDS = (
    "salary", "compensation", "pay range", "pay for", "base pay", "base salary",
    "annual", "annually", "per year", "/year", "/yr", "a year",
    "target cash", "range for this", "hiring range", "wage",
)


def _prose_compensation_all(body: str) -> list[dict]:
    """EVERY employer pay range written into the JD prose, in document order, as
    `[{"value": "<range>", "line": "<the source line, verbatim>"}, ...]`.

    Collecting all of them (this used to stop at the first match) is what lets a
    multi-zone prose posting feed the full applicable-bands envelope instead of
    collapsing to whichever band happened to appear first. The verbatim `line` is what
    populates the EMPLOYER-PROVIDED SOURCE block when no structured field carried comp.
    """
    if not body:
        return []
    # Scan the whitespace-collapsed body (so a keyword and its range can sit on different
    # source lines, as they routinely do), then map each match back to its own line for the
    # verbatim record.
    text = re.sub(r"\s+", " ", body)
    low = text.lower()
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in body.splitlines()]
    lines = [ln for ln in lines if ln]
    out: list[dict] = []
    seen: set[str] = set()
    for m in _PAY_RANGE_RE.finditer(text):
        lo, hi = m.group("lo"), m.group("hi")
        has_cur = bool(m.group("cur1") or m.group("cur2"))
        has_comma_or_k = any(("," in x or "k" in x.lower()) for x in (lo, hi))
        window = low[max(0, m.start() - 90): m.start()]
        after = low[m.end(): m.end() + 25]
        has_kw = (any(k in window for k in _SALARY_KEYWORDS)
                  or any(k in after for k in ("per year", "annually", "/yr", "/year",
                                              "a year", "base", "salary")))
        # A currency marker is enough; a comma/K-scaled figure needs a salary keyword;
        # a bare plain-digit range (240000-334000) needs an explicit currency so ids
        # and year ranges can't masquerade as pay.
        if not (has_cur or (has_comma_or_k and has_kw)):
            continue
        value = re.sub(r"\s+", " ", m.group(0)).strip()
        key = _norm_val(value)
        if key in seen:
            continue
        seen.add(key)
        source_line = next((ln for ln in lines if value in ln), value)
        out.append({"value": value, "line": source_line})
    return out


def _prose_compensation(body: str) -> str | None:
    """The FIRST employer pay figure written into the JD prose (back-compatible single
    value; `_prose_compensation_all` returns every match). Returns a cleaned range
    string, or None."""
    found = _prose_compensation_all(body)
    return found[0]["value"] if found else None


# US state abbreviations, to keep the "City, ST" prose pattern from matching noise.
_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}
# Inter-word separator is [ \t], NOT \s: \s matches newlines, which let a city glue
# onto the trailing token of the PREVIOUS line across a break ("Google Cloud\nAustin,
# TX" -> captured as one city). Keeping it on a single line fixes that (2026-07-29 audit).
_CITY_STATE_RE = re.compile(r"\b([A-Z][A-Za-z.\-]+(?:[ \t][A-Z][A-Za-z.\-]+){0,2}),[ \t]*([A-Z]{2})\b")
_REMOTE_RE = re.compile(
    r"(?i)\b(fully[- ]remote|remote[- ]first|remote[- ]friendly|100%\s*remote|"
    r"work from (home|anywhere)|this (role|position) is remote|remote position|"
    r"remote role|remote,|remote \(|open to remote)\b")
_CADENCE_RE = re.compile(
    r"(?i)\b(hybrid|on-?site|in-?office|in the office|in[- ]person|"
    r"\d\s*days?\s*(?:per|a)\s*week|days?\s*(?:per|a)\s*week in|relocate to)\b")
# The keyword group is \b-terminated so a plural nav label ("Locations" / "Office
# locations") does NOT match "location" and leak its trailing "s" as the value — the
# 2026-07-29 completeness audit caught exactly this (4 jobs green-lit with
# working-location = "s"). A separator stays optional so "Location New York" still works.
_LOC_LABEL_RE = re.compile(
    r"(?im)^\s*(?:office location|work location|location|based in)\b\s*[:\-–]?\s*(.+)$")

# A trailing marketing sentence or markdown-link/URL after the real place, captured by
# a naive prose grab (e.g. Rippling: "San Francisco, CA, [Rippling has raised ...](url) …").
_LOC_TRAILING_JUNK_RE = re.compile(r"\s*(?:\[|\(|https?://|www\.).*$", re.S)
# Bare nav/label tokens that must never count as a location on their own.
_LOC_NAV_BLOCKLIST = {"locations", "location", "careers", "apply", "menu", "jobs", "home", "s"}


def _sanitize_location(val: str | None) -> str | None:
    """Clean a raw prose location candidate and confirm it actually looks like a
    location before the completeness gate is allowed to call working-location `found`.
    Returns a short trustworthy snippet, or None (-> capture_failed downstream).

    Handles the failure modes the 2026-07-29 audit surfaced:
      "Google Cloud\\nAustin, TX" -> "Austin, TX"      (division prefix / multiline)
      "Product\\nMenlo Park, CA"  -> "Menlo Park, CA"
      "San Francisco, CA, [Rippling has raised ...](url) …" -> "San Francisco, CA"
      "s" / "Locations"          -> None              (nav-label leak)
    """
    if not val:
        return None
    # Multiline: keep the single most location-like line (City,ST > remote/cadence).
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", val) if ln.strip()]
    if lines:
        lines.sort(key=lambda ln: (
            2 if _CITY_STATE_RE.search(ln) else 1 if (_REMOTE_RE.search(ln) or _CADENCE_RE.search(ln)) else 0),
            reverse=True)
        val = lines[0]
    # A real "City, ST" anywhere wins — drops any division prefix or trailing marketing.
    cm = _CITY_STATE_RE.search(val)
    if cm and cm.group(2) in _US_STATES:
        return f"{cm.group(1)}, {cm.group(2)}"
    # Otherwise cut a trailing URL / markdown link / parenthetical marketing tail.
    val = _LOC_TRAILING_JUNK_RE.sub("", val).strip(" ,;:·—–-\t").strip()
    if len(val) < 3 or val.lower() in _LOC_NAV_BLOCKLIST:
        return None
    # Trust it if it carries a real workplace signal (Remote/hybrid/onsite/cadence),
    # or reads as a compact "City, Region" phrase (US or international). A longer
    # free-text clause with no such signal is prose, not a location.
    if _REMOTE_RE.search(val) or _CADENCE_RE.search(val):
        return val[:120]
    if "," in val and len(val.split()) <= 6 and re.match(r"^[A-Z][\w.\-]+", val):
        return val[:120]
    return None


def _prose_city_states(body: str, limit: int = 6) -> list[str]:
    """EVERY distinct "City, ST" the JD prose names, in document order (deduped, capped).

    This used to return only the FIRST match, which silently dropped employer-listed
    offices — an Airbnb posting listing both San Francisco, CA and New York, NY came out
    as SF only. The archival capture must preserve every office the employer listed."""
    out: list[str] = []
    seen: set[str] = set()
    for cm in _CITY_STATE_RE.finditer(body or ""):
        if cm.group(2) not in _US_STATES:
            continue
        place = f"{cm.group(1)}, {cm.group(2)}"
        key = place.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(place)
        if len(out) >= limit:
            break
    return out


def _prose_working_location_detail(body: str) -> tuple[str | None, str | None]:
    """(value, verbatim_source_line) for the job location/cadence written into the JD
    prose. The verbatim line is what fills the EMPLOYER-PROVIDED SOURCE block when no
    structured location field exists."""
    if not body:
        return None, None

    def _line_for(needle: str) -> str | None:
        for raw in (body or "").splitlines():
            ln = re.sub(r"\s+", " ", raw).strip()
            if ln and needle and needle.lower() in ln.lower():
                return ln
        return None

    m = _LOC_LABEL_RE.search(body)
    if m and m.group(1).strip():
        cleaned = _sanitize_location(m.group(1))
        if cleaned:
            return cleaned, re.sub(r"\s+", " ", m.group(0)).strip()
    m = _REMOTE_RE.search(body)
    if m:
        value = m.group(0).strip().rstrip(",(").strip().title()
        return value, _line_for(m.group(0).strip())
    cities = _prose_city_states(body)
    if cities:
        return "; ".join(cities), _line_for(cities[0])
    m = _CADENCE_RE.search(body)
    if m:
        return m.group(0).strip(), _line_for(m.group(0).strip())
    return None, None


def _prose_working_location(body: str) -> str | None:
    """Best-effort job location/cadence written into the JD prose: EVERY named "City, ST"
    (`"; "`-joined), a Remote/hybrid/onsite signal, or an explicit Location: line. Returns a
    short, validated snippet, or None. Every candidate is run through _sanitize_location so
    a nav-label leak ("Locations" -> "s") or a marketing tail never counts as found."""
    return _prose_working_location_detail(body)[0]


# --------------------------------------------------------------------------- #
# Conflict producers — "materially disagree" = DISJOINT envelopes
#
# The CONFLICTING status and the `[CONFLICT]:` line have existed for a while but were
# UNREACHABLE: nothing in production ever populated `compensation_sources` /
# `location_sources`, so a real ATS-vs-prose disagreement was never detected. These helpers
# are the missing producers. The bar is deliberately conservative — identical or merely
# overlapping figures must NOT flag (a posting that repeats its structured range in the
# prose is the common case, not a conflict); only genuinely disjoint readings do.
# --------------------------------------------------------------------------- #
def _thousands_envelope(text: str) -> tuple[float, float] | None:
    """(min, max) of every plausible base-salary figure in a comp string, in whole
    thousands. `$236K – $296K` -> (236, 296); `USD 213,000-266,000` -> (213, 266)."""
    vals: list[float] = []
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*([kK])?\b", str(text or "")):
        raw = m.group(1).replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        if not m.group(2) and v >= 10000:
            v = v / 1000.0
        if not (10 <= v <= 2000):
            continue
        vals.append(v)
    return (min(vals), max(vals)) if vals else None


def _comp_materially_disagrees(structured: str, prose_values: list[str]) -> bool:
    """True only when the structured and prose comp envelopes are DISJOINT."""
    a = _thousands_envelope(structured)
    b = _thousands_envelope(" ".join(prose_values))
    if not a or not b:
        return False
    return a[1] < b[0] or b[1] < a[0]


def _location_materially_disagrees(structured: str, prose_cities: list[str]) -> bool:
    """True only when BOTH sides name "City, ST" places and the city sets are disjoint."""
    a = {c.split(",")[0].strip().lower() for c in _prose_city_states(str(structured or ""), limit=12)}
    b = {c.split(",")[0].strip().lower() for c in prose_cities}
    if not a or not b:
        return False
    return a.isdisjoint(b)


def assess_completeness(meta: dict | None, body: str, questions: list | None) -> dict:
    """Per-field capture status for the ranking gate. Each of compensation and
    working-location (plus title/description presence) is exactly one of:
    `found` / `not_posted` / `capture_failed` / `conflicting`.

    Rules (PII-free; candidate-relative interpretation happens later at vetting):
      - Employer compensation must be a real employer figure. A candidate
        "compensation expectations?" question does NOT satisfy it (such questions
        are already dropped by the filter and never reach here).
      - Working location must be the JOB's location/cadence. "Where do you live?"
        does NOT satisfy it; an office-attendance question DOES (and supplies the
        cadence). Two disagreeing sources -> `conflicting` (keep both, flagged).
    """
    meta = meta or {}
    questions = questions or []
    fs: dict = {"conflicts": []}

    title = (meta.get("title") or "").strip()
    fs["title"] = FOUND if title and title != "Unknown Title" else CAPTURE_FAILED
    fs["description"] = FOUND if (body or "").strip() else CAPTURE_FAILED

    # ---- compensation ----
    comp_sources = _distinct([s for _, s in (meta.get("compensation_sources") or [])] or [meta.get("compensation")])
    comp_from_q = any(question_provides_employer_comp(q) for q in questions)
    comp_prose_all = _prose_compensation_all(body)
    comp_prose = comp_prose_all[0]["value"] if comp_prose_all else None
    if comp_prose_all:
        # Keep every prose band machine-readably (it rides into the manifest entry via
        # field_status) so the applicable-bands envelope isn't limited to the first match.
        fs["compensation_prose_all"] = [c["value"] for c in comp_prose_all]
        fs["compensation_prose_verbatim"] = comp_prose_all[0]["line"]
    # Conflict producer: a structured ATS figure AND a prose figure that materially
    # disagree (disjoint envelopes) -> synthesize the two sources so the CONFLICTING
    # branch below fires and BOTH readings are preserved, never silently picked.
    if len(comp_sources) < 2 and meta.get("compensation") and comp_prose_all:
        if _comp_materially_disagrees(meta["compensation"], fs.get("compensation_prose_all") or []):
            label = str(meta.get("source") or "structured")
            synthesized = [(label, str(meta["compensation"])),
                           ("description", "; ".join(fs["compensation_prose_all"]))]
            fs["compensation_sources"] = synthesized
            comp_sources = _distinct([s for _, s in synthesized])
    if len(comp_sources) >= 2:
        fs["compensation"] = CONFLICTING
        fs["conflicts"].append(f"compensation: {' vs '.join(comp_sources[:2])}")
    elif meta.get("compensation") or comp_from_q:
        fs["compensation"] = FOUND
    elif comp_prose:
        # The scorer reads the JD body; comp is written into the prose even though no
        # structured field carried it. This IS found — not a capture failure.
        fs["compensation"] = FOUND
        fs["compensation_source"] = "description"
        fs["compensation_prose"] = comp_prose
    elif meta.get("comp_expected"):
        # A structured source expected comp but it came back empty -> capture failure.
        fs["compensation"] = CAPTURE_FAILED
    elif _source_is_structured(meta):
        # A structured source was consulted and comp is genuinely absent (e.g.
        # Greenhouse pay_transparency with empty pay_input_ranges, Ashby
        # shouldDisplayCompensationOnJobPostings=false, JSON-LD with no salary).
        fs["compensation"] = NOT_POSTED
    else:
        # A bare generic HTML scrape: a missing figure is could-not-verify, not
        # proof the employer didn't publish (this is the field-driven retry trigger).
        fs["compensation"] = CAPTURE_FAILED

    # ---- working location ----
    loc_sources = _distinct([s for _, s in (meta.get("location_sources") or [])]
                            or [meta.get("working_location") or meta.get("location")])
    office_q = any(question_provides_working_location(q) for q in questions)
    loc_prose, loc_prose_line = _prose_working_location_detail(body)
    if loc_prose_line:
        fs["working_location_prose_verbatim"] = loc_prose_line
    structured_loc = meta.get("working_location") or meta.get("location")
    if len(loc_sources) < 2 and structured_loc:
        prose_cities = _prose_city_states(body)
        if _location_materially_disagrees(structured_loc, prose_cities):
            label = str(meta.get("source") or "structured")
            synthesized = [(label, str(structured_loc)), ("description", "; ".join(prose_cities))]
            fs["location_sources"] = synthesized
            loc_sources = _distinct([s for _, s in synthesized])
    if len(loc_sources) >= 2:
        fs["working_location"] = CONFLICTING
        fs["conflicts"].append(f"working-location: {' vs '.join(loc_sources[:2])}")
    elif meta.get("working_location") or meta.get("location") or office_q:
        fs["working_location"] = FOUND
    elif loc_prose:
        # Location written into the JD prose (a named city / Remote / cadence) — the
        # scorer can read it, so it is found, not a capture failure.
        fs["working_location"] = FOUND
        fs["working_location_source"] = "description"
        fs["working_location_prose"] = loc_prose
    elif meta.get("location_expected"):
        # A structured source expected a location but it came back empty.
        fs["working_location"] = CAPTURE_FAILED
    elif _source_is_structured(meta):
        # Structured source consulted; location genuinely absent.
        fs["working_location"] = NOT_POSTED
    else:
        # Generic scrape: missing location is could-not-verify (retry trigger).
        fs["working_location"] = CAPTURE_FAILED

    return fs


def missing_hard_fields(field_status: dict | None) -> list[str]:
    """Hard fields whose capture actually failed (a retry might help). `not_posted`
    and `conflicting` are NOT retryable-missing — the employer just didn't publish,
    or we already have two readings."""
    fs = field_status or {}
    return [f for f in HARD_FIELDS if fs.get(f) == CAPTURE_FAILED]


# --------------------------------------------------------------------------- #
# Output text + quarantine stubs
# --------------------------------------------------------------------------- #
_STATUS_LABEL = {
    FOUND: "found", NOT_POSTED: "not posted", CAPTURE_FAILED: "capture failed",
    CONFLICTING: "conflicting",
}


def _apply_office_cadence(meta: dict, questions: list) -> tuple[str | None, str | None]:
    """If a kept question carries an office-attendance requirement, fold its full
    eligible-metro list + cadence into the working-location string (verbatim; no
    candidate-city mapping — vetting does that from jail.config.json)."""
    working = meta.get("working_location") or meta.get("location")
    cadence_raw = meta.get("cadence_raw")
    for q in questions or []:
        parsed = parse_office_cadence(q)
        if not parsed:
            continue
        metros = parsed.get("metros") or []
        cadence = parsed.get("cadence")
        if metros:
            metro_str = "; ".join(metros)
            working = f"{working}; {metro_str}" if working else metro_str
            # Dedupe while preserving order.
            working = "; ".join(dict.fromkeys(p.strip() for p in working.split(";") if p.strip()))
        if cadence:
            working = f"{working} — {cadence}" if working else cadence
        cadence_raw = cadence_raw or parsed.get("verbatim")
    return working, cadence_raw


def build_output_text(url: str, title: str, company: str, body_text: str, *,
                      meta: dict | None = None, questions: list | None = None,
                      field_status: dict | None = None, methods_tried: list | None = None,
                      captured: str | None = None) -> str:
    """Dual-preservation layout: a provenance line, a NORMALIZED block (for
    vetting) with per-field statuses + a completeness line + optional conflicts,
    an APPLICATION QUESTIONS block (kept questions only, verbatim), a verbatim
    EMPLOYER-PROVIDED SOURCE block, then the full job text between the stable
    START/END markers. Parseable and stable (golden-file tested)."""
    meta = meta or {}
    questions = questions if questions is not None else (meta.get("questions") or [])
    fs = field_status or assess_completeness(meta, body_text, questions)

    apply_url = meta.get("apply_url") or "n/a"
    source = meta.get("source") or "requests/html"
    posting_id = meta.get("posting_id") or "n/a"
    methods = ", ".join(dict.fromkeys(methods_tried or [])) or (meta.get("method") or source)
    captured = captured or datetime.now(timezone.utc).date().isoformat()

    workplace = meta.get("workplace") or ("Remote" if meta.get("remote") else None)
    working_location, cadence_raw = _apply_office_cadence(meta, questions)
    compensation = meta.get("compensation")
    benefits = meta.get("benefits")
    equity = meta.get("equity")

    # When a field was found only in the JD prose (no structured value), surface that
    # prose figure on the line and mark it "(from description)" so the value shown
    # matches the found status and what the scorer reads.
    comp_from_prose = not compensation and fs.get("compensation_source") == "description"
    if comp_from_prose:
        compensation = fs.get("compensation_prose")
    loc_from_prose = not working_location and fs.get("working_location_source") == "description"
    if loc_from_prose:
        working_location = fs.get("working_location_prose")

    def _stat(field: str) -> str:
        return f"[{_STATUS_LABEL.get(fs.get(field), 'unknown')}]"

    def _val(v, status_field, from_prose=False):
        if v:
            return f"{v} (from description)" if from_prose else str(v)
        st = fs.get(status_field)
        return "Not posted" if st == NOT_POSTED else ("Could not verify" if st == CAPTURE_FAILED else "n/a")

    lines: list[str] = []
    lines.append(f"URL: {url}")
    lines.append(f"Application URL: {apply_url}")
    lines.append(f"Company: {company}")
    lines.append(f"Role: {title}")
    lines.append(f"Source: {source} · Posting ID: {posting_id} · Captured: {captured} · Methods tried: {methods}")
    # When the employer published a posting date, say so. `Captured:` above is OUR fetch date
    # and was previously the only date in the file, so nothing downstream could tell a
    # week-old posting from a nine-month-old one. Omitted entirely when unknown — never a
    # fabricated or inferred date.
    posted_date = meta.get("posted_date")
    updated_date = meta.get("updated_date")
    if posted_date:
        posted_line = f"Posted: {posted_date}"
        if updated_date and updated_date != posted_date:
            posted_line += f" · Updated: {updated_date}"
        lines.append(posted_line)
    lines.append("")
    lines.append("== NORMALIZED (for vetting) ==")
    lines.append(f"Employment Type: {meta.get('employment_type') or 'n/a'}")
    lines.append(f"Workplace: {workplace or 'n/a'}")
    lines.append(f"Working Location: {_val(working_location, 'working_location', loc_from_prose)}   {_stat('working_location')}")
    lines.append(f"Compensation: {_val(compensation, 'compensation', comp_from_prose)}   {_stat('compensation')}")
    lines.append(f"Benefits: {benefits or 'Not posted'}")
    lines.append(f"Equity: {equity or 'Not posted'}")
    lines.append(
        f"Completeness: title {'✓' if fs.get('title') == FOUND else '✗'} · "
        f"description {'✓' if fs.get('description') == FOUND else '✗'} · "
        f"compensation {_STATUS_LABEL.get(fs.get('compensation'), 'unknown')} · "
        f"working-location {_STATUS_LABEL.get(fs.get('working_location'), 'unknown')}"
    )
    for c in (fs.get("conflicts") or []):
        lines.append(f"[CONFLICT]: {c}")
    lines.append("")
    lines.append("== APPLICATION QUESTIONS (thoughtful / job-material only) ==")
    if questions:
        for i, q in enumerate(questions, 1):
            req = "required" if q.get("required") else "optional"
            qtype = q.get("source_type") or q.get("type") or "text"
            help_txt = f" — {q['help']}" if q.get("help") else ""
            opts = q.get("options") or []
            opt_str = "  (options: " + " / ".join(f'"{o}"' for o in opts) + ")" if opts else ""
            label = _strip_wrapping_quotes(q.get("label", "").strip())
            lines.append(f'{i}. [{qtype}, {req}] "{label}"{help_txt}{opt_str}')
    else:
        lines.append("(none kept)")
    lines.append("")
    lines.append("== EMPLOYER-PROVIDED SOURCE (verbatim; the durable archive) ==")
    # When no structured field carried comp/location, the verbatim archive falls back to the
    # employer's own PROSE LINE that the value was mined from. These used to render as empty
    # quotes even when the body was full of comp/location language (an Airbnb regression):
    # the durable archive must not look blank when the employer did publish the wording.
    comp_verbatim = meta.get("compensation_raw") or fs.get("compensation_prose_verbatim") or ""
    loc_verbatim = meta.get("location_raw") or fs.get("working_location_prose_verbatim") or ""
    cadence_verbatim = cadence_raw
    if not cadence_verbatim:
        prose_line = fs.get("working_location_prose_verbatim") or ""
        if prose_line and _CADENCE_RE.search(prose_line):
            cadence_verbatim = prose_line
    lines.append(f'Compensation (verbatim): "{comp_verbatim}"')
    lines.append(f'Locations/Addresses (verbatim): "{loc_verbatim}"')
    lines.append(f'Office cadence (verbatim): "{cadence_verbatim or ""}"')
    # Present only when the Application URL above was replaced by a canonical ATS deep link
    # because the employer's own apply URL was a listing/search page that merely redirects.
    if meta.get("employer_apply_url"):
        lines.append(f'Employer apply page (verbatim): {meta["employer_apply_url"]}')
    lines.append("")
    lines.append("--- JOB TEXT START ---")
    lines.append("")
    lines.append(body_text)
    lines.append("")
    lines.append("--- JOB TEXT END ---")
    return "\n".join(lines) + "\n"


def thin_text(url: str, title: str, company: str, body_text: str, reason: str, ts: str,
              *, meta: dict | None = None, questions: list | None = None,
              field_status: dict | None = None, methods_tried: list | None = None) -> str:
    return (
        f"# QUARANTINED — THIN FETCH (needs your review)\n"
        f"# Reason: {reason}\n"
        f"# Fetched: {ts}\n"
        f"# What to do: open this, confirm it's the real job post. If it's incomplete,\n"
        f"#   paste the full job text below the marker, then re-run prep (it will pick it up),\n"
        f"#   OR move this file into 'All Job Posts (full text)/' if it's actually fine.\n\n"
        + build_output_text(url, title, company, body_text, meta=meta, questions=questions,
                            field_status=field_status, methods_tried=methods_tried)
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
    batch = sm.parent          # batch root (__READY_TO_REVIEW__PRIVATE_GITIGNORED/MM-DD-YY)
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
    # Usable posts still missing a hard field (comp / working-location). These rank
    # anyway — but loudly flagged, distinguishing "employer didn't publish" from
    # "expected from the ATS but came back empty".
    incomplete = [x for x in usable
                  if any((x.get("field_status") or {}).get(f) in (CAPTURE_FAILED, NOT_POSTED, CONFLICTING)
                         for f in HARD_FIELDS)]
    # Usable posts whose JOB TITLE could not be captured (the page offered only careers-site
    # branding and no real title was recoverable from JSON-LD / headings / body). Flagged
    # separately and loudly: the capture is still rankable, but its filename and `Role:` line
    # are placeholders, so paste the real title (or re-fetch) before tailoring anything.
    titleless = [x for x in usable if (x.get("field_status") or {}).get("title") == CAPTURE_FAILED]
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
    if incomplete:
        lines.append(f"- ⚠️ {len(incomplete)} usable post(s) with an incomplete comp/location capture — see below")
    if titleless:
        lines.append(f"- 🚨 {len(titleless)} usable post(s) whose JOB TITLE could not be captured — see below")
    lines += ["", "## Details"]
    if titleless:
        lines.append("**🚨 Job title not captured (the page gave only careers-site branding):**")
        for x in titleless:
            lines.append(f"- {x.get('company','?')} — title unknown; the capture's `Role:` line and "
                         f"filename are placeholders. Paste the real title into the file or re-fetch "
                         f"before tailoring.  ({x['original_url']})")
    if incomplete:
        lines.append("**⚠️ Incomplete captures (still ranked — review the flagged field):**")
        for x in incomplete:
            fsx = x.get("field_status") or {}
            bits = []
            for f in HARD_FIELDS:
                st = fsx.get(f)
                if st == CAPTURE_FAILED:
                    bits.append(f"{f.replace('_', '-')}: capture failed (expected from "
                                f"{x.get('method') or 'source'} but came back empty)")
                elif st == NOT_POSTED:
                    bits.append(f"{f.replace('_', '-')}: not posted (employer didn't publish)")
                elif st == CONFLICTING:
                    bits.append(f"{f.replace('_', '-')}: conflicting (two sources disagree — both kept)")
            lines.append(f"- {x.get('company','?')} — {x.get('title','?')}: {'; '.join(bits)}  ({x['original_url']})")
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
def process_urls(urls: list[str], source_dir, fetch_one, *, force: bool = False,
                  fetch_fallback=None, fallback_label: str | None = None) -> dict:
    """fetch_one(url) -> dict: {ok: bool, title, company, body, method, error}.
    Manifest-aware: a plain re-run skips already-usable URLs and retries
    thin/failed ones (set force=True to refetch everything).

    HARD RULE (Jessica, 7/16/26): a job must never be scored against content nobody has
    confirmed is the real posting. Before quarantining a THIN/FAILED result, always try a
    SECOND fetch method if one is available (fetch_fallback — same signature as fetch_one).
    Only after both methods fail does a URL get quarantined, and the quarantine notes then
    say plainly that multiple methods were attempted and both failed. If no fallback is
    available at all (e.g. Playwright isn't installed), that limitation is recorded in the
    manifest/report too, rather than silently only trying once."""
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
             "possible_duplicate_group": None, "notes": "", "error": None, "fetched_at": ts,
             # Completeness gate (comp + working-location before ranking). A missing
             # hard field never quarantines — the job stays usable and ranks, flagged.
             "field_status": None, "missing_fields": [], "methods_tried": [],
             "has_compensation": None, "has_working_location": None,
             # Employer posting dates (plain YYYY-MM-DD, or None when the source has none) —
             # the rankings `Posted` column reads these back out of the capture.
             "posted_date": None, "updated_date": None}
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

        def _evaluate(r):
            """(status, reason, field_status) for one fetch result."""
            if not r.get("ok"):
                return FAILED, (r.get("error") or "fetch failed"), {}
            st, rs = classify(r.get("body") or "", is_ats=(r.get("method") == "ats"))
            f_status = assess_completeness(r.get("meta") or {}, r.get("body") or "",
                                           r.get("questions") if r.get("questions") is not None
                                           else (r.get("meta") or {}).get("questions"))
            return st, rs, f_status

        res = fetch_one(url) or {}
        methods_tried = [res.get("method") or "unknown"]
        status, reason, field_status = _evaluate(res)

        # HARD RULE: never quarantine on one method alone if a second one is available.
        # The fallback fetch fires when the first attempt is THIN/FAILED *or* when a hard
        # field (compensation / working-location) came back as a genuine capture failure
        # (field-driven, not just body-thinness) — this is the completeness gate that
        # runs BEFORE ranking, so we don't rank an incomplete capture then re-fetch later.
        field_gap = missing_hard_fields(field_status)
        if (status != USABLE or field_gap) and fetch_fallback is not None:
            res2 = fetch_fallback(url) or {}
            methods_tried.append(res2.get("method") or fallback_label or "fallback")
            status2, reason2, field_status2 = _evaluate(res2)
            gap2 = missing_hard_fields(field_status2)
            improved_body = status2 == USABLE or (status == FAILED and status2 == THIN)
            improved_fields = status2 == USABLE and len(gap2) < len(field_gap)
            if improved_body or improved_fields:
                res, status, reason, field_status, field_gap = res2, status2, reason2, field_status2, gap2
            if status != USABLE:
                reason = f"{reason} (tried {', '.join(methods_tried)}, all failed to produce usable content)"
        elif status != USABLE and fetch_fallback is None:
            reason = (f"{reason} — only one fetch method attempted ({methods_tried[0]}); "
                      f"no fallback method available (e.g. Playwright not installed) to auto-retry")

        # Embedded-Greenhouse recovery: many custom career domains (careers.<co>.com)
        # are Greenhouse-backed. If we still lack a hard field (or never got usable
        # content), and this non-ATS URL carries a Greenhouse-style job id, hit the
        # real GH boards API with board tokens derived from the domain / page HTML.
        # Accepted only when the returned title matches what we already have (guards
        # a wrong-board-token collision) — this is what lets e.g. Airbnb recover
        # comp + location a plain scrape of careers.airbnb.com misses.
        if status != USABLE or field_gap:
            rec = recover_embedded_greenhouse(
                url, page_title=res.get("title"), body=res.get("body"),
                html_text=(res.get("meta") or {}).get("raw_html"))
            if rec:
                methods_tried.append("greenhouse-embedded")
                rec_meta = dict(rec)
                rec_meta["method"] = "ats"
                rec_meta["structured_source"] = True
                res_rec = {"ok": True, "title": rec.get("title"),
                           "company": rec.get("company"), "body": rec.get("text") or "",
                           "method": "ats", "error": None, "meta": rec_meta,
                           "questions": rec.get("questions") or []}
                status_r, reason_r, field_status_r = _evaluate(res_rec)
                gap_r = missing_hard_fields(field_status_r)
                if status_r == USABLE and (status != USABLE or len(gap_r) < len(field_gap)):
                    res, status, reason, field_status, field_gap = (
                        res_rec, status_r, reason_r, field_status_r, gap_r)

        if status == FAILED:
            fn = failed_filename(url, norm)
            out = dirs["failed"] / fn
            out.write_text(failed_text(url, reason, ts), encoding="utf-8")
            entries.append(base_entry(url, norm, status=FAILED, method=res.get("method"),
                                      error=reason, notes=f"methods tried: {', '.join(methods_tried)}",
                                      methods_tried=methods_tried,
                                      quarantine_path=_rel(out, batch_root)))
            continue

        title = (res.get("title") or "Unknown Title").strip()
        company = (res.get("company") or "Unknown").strip()
        body = res.get("body") or ""
        method = res.get("method")
        meta = res.get("meta") or {}
        # THE choke point for captured identity: whichever fetch path won above, its
        # (company, title) pair is canonicalized here — once — before the filename, the
        # header, and the manifest entry are derived from it. Idempotent per URL.
        company, title = normalize_capture_identity(
            company, title, url=url, jsonld=meta.get("jsonld_identity"),
            html=meta.get("raw_html"), body=body)
        meta["company"], meta["title"] = company, title
        # The title status was assessed against the RAW scraped title; re-derive it from
        # the canonical one so a branding-only title that could not be recovered shows up
        # as a capture failure in the completeness line, the manifest, and the report.
        field_status["title"] = FOUND if title != "Unknown Title" else CAPTURE_FAILED
        questions = res.get("questions") if res.get("questions") is not None else meta.get("questions")
        missing = missing_hard_fields(field_status)
        has_comp = field_status.get("compensation") == FOUND
        has_loc = field_status.get("working_location") == FOUND

        fn = unique_filename(company, title, norm, taken, url)
        taken[fn] = norm
        out_text = build_output_text(url, title, company, body, meta=meta, questions=questions,
                                     field_status=field_status, methods_tried=methods_tried)
        if status == USABLE:
            out = dirs["source"] / fn
            out.write_text(out_text, encoding="utf-8")
            note_bits = []
            if len(methods_tried) > 1:
                note_bits.append(f"usable after fallback (tried: {', '.join(methods_tried)})")
            if field_status.get("title") == CAPTURE_FAILED:
                note_bits.append("job title capture failed — the page gave only site branding "
                                 "and no real role title could be recovered")
            if missing:
                note_bits.append("incomplete capture: " + ", ".join(
                    f"{f.replace('_', '-')} {field_status.get(f)}" for f in missing))
            entries.append(base_entry(url, norm, status=USABLE, method=method, company=company,
                                      title=title, char_count=len(body), notes="; ".join(note_bits),
                                      field_status=field_status, missing_fields=missing,
                                      methods_tried=methods_tried, has_compensation=has_comp,
                                      has_working_location=has_loc,
                                      posted_date=meta.get("posted_date"),
                                      updated_date=meta.get("updated_date"),
                                      output_path=_rel(out, batch_root)))
        else:  # THIN
            out = dirs["needs_review"] / fn
            out.write_text(thin_text(url, title, company, body, reason, ts, meta=meta,
                                     questions=questions, field_status=field_status,
                                     methods_tried=methods_tried), encoding="utf-8")
            entries.append(base_entry(url, norm, status=THIN, method=method, company=company,
                                      title=title, char_count=len(body), notes=reason,
                                      field_status=field_status, missing_fields=missing,
                                      methods_tried=methods_tried, has_compensation=has_comp,
                                      has_working_location=has_loc,
                                      posted_date=meta.get("posted_date"),
                                      updated_date=meta.get("updated_date"),
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
