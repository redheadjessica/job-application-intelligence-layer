#!/usr/bin/env python3
"""Render-based fetcher (Playwright) — the deeper fallback / retry engine for
JS-rendered pages that come back thin from the requests fetcher. Shares all the
dedupe / classify / quarantine / manifest / report logic via prep_common; this
file only knows how to RENDER and extract one URL.

    python prep_job_urls_playwright.py "<source folder>" --input "<urls.txt>" [--force]

Manifest-aware like the primary fetcher: a plain re-run retries the thin/failed
URLs (rendering them) and leaves already-usable ones alone. Beginners don't need
this directly — it's the retry path for stubborn posts.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import prep_common
from ats_fetchers import (
    ats_company_from_url,
    detect_apply_ats,
    extract_jsonld_jobposting,
    fetch_via_ats,
    filter_questions,
    normalize_apply_fields,
    normalize_ashby_apply_fields,  # noqa: F401  (back-compat alias re-export)
)

LIKELY_SELECTORS = [
    "main", "article", "[data-testid*='job']", "[class*='job-description']",
    "[class*='jobDescription']", "[class*='description']", "[class*='posting']",
    "[class*='content']", "[class*='careers']", "[id*='job-description']",
    "[id*='description']", "[id*='content']",
]


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def detect_company_from_url(url: str) -> str:
    ats_company = ats_company_from_url(url)
    if ats_company:
        return ats_company
    host = urlparse(url).netloc.lower().replace("www.", "")
    parts = host.split(".")
    company = parts[-2] if len(parts) >= 2 else host
    return company.replace("-", " ").title()


# A title segment carrying "careers"/"jobs" ANYWHERE is site branding, not an employer name.
# This used to be an exact-set membership test ({"careers", "jobs", ...}), so "Careers at
# Airbnb" sailed through as the company and produced `careers-at-airbnb__…txt`. A pattern
# test rejects the whole family ("Careers at X", "X Careers", "Jobs at X", "View all jobs").
# Anything that still slips through as the ROLE segment is repaired downstream by
# prep_common.normalize_capture_identity (the never-role-as-company guard).
_TITLE_SEGMENT_BRANDING_RE = re.compile(r"\b(careers?|jobs?)\b", re.I)


def best_company_from_title(title: str, fallback: str) -> str:
    parts = [p.strip() for p in re.split(r"\||•|-", title or "") if p.strip()]
    for part in reversed(parts):
        if len(part) <= 60 and not _TITLE_SEGMENT_BRANDING_RE.search(part):
            return part
    return fallback


def extract_best_text(page) -> str:
    candidates = []
    for selector in LIKELY_SELECTORS:
        try:
            for el in page.locator(selector).all()[:8]:
                try:
                    text = clean_text(el.inner_text(timeout=2000))
                    if len(text) >= 500:
                        candidates.append((len(text), selector, text))
                except Exception:
                    pass
        except Exception:
            pass
    try:
        full = clean_text(page.locator("body").inner_text(timeout=3000))
        if len(full) >= 500:
            candidates.append((len(full), "body", full))
    except Exception:
        pass
    if not candidates:
        return ""
    candidates.sort(key=lambda x: (x[0] - (500 if x[1] == "body" else 0)), reverse=True)
    return candidates[0][2]


def ashby_apply_url(url: str) -> str:
    """Build an Ashby apply-page URL from a job URL.

    BUG FIX (2026-07-29): this used to be `url.rstrip('/') + '/application'`, which
    silently produced a broken URL whenever the job URL carried a query string —
    e.g. `.../<id>?src=LinkedIn` became `.../<id>?src=LinkedIn/application`, so the
    apply page never loaded and question capture degraded to [] with no error. Real
    URLs from LinkedIn/job boards almost ALWAYS carry `?src=`, `?departmentId=`, or
    `?utm_source=`, so in practice question capture was failing for nearly every
    Ashby job while the clean-URL test case passed (false confidence). Build the
    apply URL from the PATH only and drop query/fragment."""
    p = urlparse(url)
    path = (p.path or "").rstrip("/")
    if not path.endswith("/application"):
        path += "/application"
    return f"{p.scheme or 'https'}://{p.netloc}{path}"


def lever_apply_url(url: str) -> str:
    """Build a Lever apply-page URL from a job URL (path only; query/fragment
    dropped — same rule as `ashby_apply_url`)."""
    p = urlparse(url)
    path = (p.path or "").rstrip("/")
    if not path.endswith("/apply"):
        path += "/apply"
    return f"{p.scheme or 'https'}://{p.netloc}{path}"


def workable_apply_url(url: str) -> str:
    """Build a Workable apply-page URL: apply.workable.com/{sub}/j/{code}/apply/."""
    p = urlparse(url)
    path = (p.path or "").rstrip("/")
    if not path.endswith("/apply"):
        path += "/apply"
    return f"{p.scheme or 'https'}://{p.netloc}{path}/"


def homerun_apply_url(url: str) -> str:
    """Build a Homerun apply-page URL: {job-url}/apply (it redirects to the
    localized `/en/apply?step=1` form)."""
    p = urlparse(url)
    path = (p.path or "").rstrip("/")
    if not path.endswith("/apply"):
        path += "/apply"
    return f"{p.scheme or 'https'}://{p.netloc}{path}"


# ATSes whose application questions exist ONLY on the rendered apply page (their
# job API returns none), mapped to the apply-URL builder for that ATS. Rippling and
# Greenhouse are absent on purpose — their APIs return the questions inline, so
# rendering them would be pure cost.
APPLY_URL_BUILDERS = {
    "ashby": ashby_apply_url,
    "lever": lever_apply_url,
    "workable": workable_apply_url,
    "homerun": homerun_apply_url,
}


def apply_page_url(url: str, ats: str | None = None) -> str | None:
    """The apply-page URL for a job URL, or None when this ATS's questions are not
    behind an apply page (or the ATS is unknown)."""
    ats = ats or detect_apply_ats(url)
    builder = APPLY_URL_BUILDERS.get(ats or "")
    return builder(url) if builder else None


# One DOM scrape for every apply page. The container/label/control walk is generic:
# each ATS renders a labeled field container, and the label's control is either
# inside it or referenced by `for=`. Selectors are additive per ATS, never forked.
_APPLY_FIELD_SCRAPE_JS = """() => {
    const out = [];
    const seen = new Set();
    const conts = document.querySelectorAll([
        '.ashby-application-form-field-entry',
        '[class*="_fieldEntry"]',
        '[data-ui="field"]',
        '.application-question',
        '.application-field',
        'form label',
        'form fieldset'
    ].join(','));
    const control = (c) => {
        // The control usually lives inside the container. When the container IS a
        // bare <label> (Homerun, some Lever cards) it can be the label's `for=`
        // target or an adjacent sibling instead — check those too, or every essay
        // textarea is misread as a plain text input and dropped as non-compose.
        let el = c.querySelector('textarea, select, input');
        if (el) return el;
        const forId = c.getAttribute && c.getAttribute('for');
        if (forId) {
            const t = document.getElementById(forId);
            if (t) return t;
        }
        for (const sib of [c.nextElementSibling, c.parentElement]) {
            if (!sib) continue;
            el = sib.matches && sib.matches('textarea, select, input')
                ? sib : (sib.querySelector ? sib.querySelector('textarea, select, input') : null);
            if (el) return el;
        }
        return null;
    };
    conts.forEach(c => {
        const labelEl = c.querySelector('label, legend, .ashby-application-form-question-title') || c;
        const title = (labelEl.innerText || labelEl.textContent || '').trim();
        if (!title || seen.has(title)) return;
        const el = control(c);
        let type = 'String', options = [];
        if (el) {
            const tag = el.tagName.toLowerCase();
            if (tag === 'textarea') type = 'LongText';
            else if (tag === 'select') {
                type = 'ValueSelect';
                el.querySelectorAll('option').forEach(o => {
                    const t = (o.textContent || '').trim();
                    if (t) options.push({label: t});
                });
            } else {
                const it = (el.getAttribute('type') || '').toLowerCase();
                if (it === 'checkbox' || it === 'radio') type = 'Boolean';
                else if (it === 'file') type = 'File';
                else type = 'String';
            }
        }
        const path = el ? (el.getAttribute('name') || el.getAttribute('id') || '') : '';
        seen.add(title);
        out.push({title, type, path, isRequired: !!(el && el.required), options});
    });
    return out;
}"""


def render_apply_questions(browser, url: str, apply_url_hint: str | None = None,
                           ats: str | None = None) -> list:
    """Best-effort scrape of an apply page's form fields, for every ATS whose job
    API does not carry them (Ashby, Lever, Workable, Homerun). The fields are
    normalized and run through the shared narrow filter, so only the thoughtful /
    job-material questions (compose essays, office cadence) survive.

    Raises on render failure rather than swallowing it — the caller prints the
    exception and degrades to []. A silently-empty result is exactly what hid the
    broken Ashby apply-URL builder for months."""
    # Prefer the ATS-provided apply URL when we have one: it is canonical and also
    # handles CUSTOM-DOMAIN jobs (e.g. `lark.com/careers?ashby_jid=<uuid>`), whose
    # own host/path can't be turned into an apply URL at all.
    ats = ats or detect_apply_ats(apply_url_hint, url)
    apply_url = apply_page_url(apply_url_hint or url, ats)
    if not apply_url:
        return []
    page = None
    try:
        page = browser.new_page()
        page.set_default_timeout(15000)
        page.goto(apply_url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PlaywrightTimeoutError:
            pass
        raw = page.evaluate(_APPLY_FIELD_SCRAPE_JS)
        fields = normalize_apply_fields({"fields": raw or []})
        return filter_questions(fields)
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass


def _render_ashby_questions(browser, url: str, apply_url_hint: str | None = None) -> list:
    """Back-compat wrapper: the renderer began Ashby-only. Callers should use
    `render_apply_questions`, which auto-detects the ATS. Kept because the primary
    fetcher and its tests wire this name in as the question-render callback."""
    return render_apply_questions(browser, url, apply_url_hint)


def make_fetch_one(browser):
    def fetch_one(url: str) -> dict:
        try:
            ats = fetch_via_ats(url)
            if ats:
                meta = dict(ats)
                meta["method"] = "ats"
                meta["structured_source"] = True
                questions = ats.get("questions") or []
                # Several ATSes keep their questions off the job API (Ashby, Lever,
                # Workable, Homerun) — render the apply page for those. Detect the
                # ATS from the apply URL / job URL / source label, NOT from the host
                # alone: custom-domain jobs (e.g. `lark.com/careers?ashby_jid=<uuid>`)
                # are served by Ashby under the employer's own domain, and a
                # host-only check skipped question capture for them entirely.
                ats_kind = detect_apply_ats(ats.get("apply_url"), url, ats.get("source"))
                if not questions and ats_kind:
                    try:
                        rendered = render_apply_questions(
                            browser, url, ats.get("apply_url"), ats_kind) or []
                    except Exception as exc:
                        # Best-effort: never fail the fetch. But never silent either —
                        # a swallowed exception is what hid the broken apply-URL
                        # builder while every test still passed.
                        print(f"  ! {ats_kind} question render failed for {url}: "
                              f"{type(exc).__name__}: {exc}")
                        rendered = []
                    if rendered:
                        questions = rendered
                        meta["questions"] = rendered
                return {"ok": True, "title": ats["title"], "company": ats["company"],
                        "body": ats["text"], "method": "ats", "error": None,
                        "meta": meta, "questions": questions}
            page = browser.new_page()
            page.set_default_timeout(15000)
            try:
                page.goto(url, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except PlaywrightTimeoutError:
                    pass
                title = page.title().strip() or "Unknown Title"
                company = best_company_from_title(title, detect_company_from_url(url))
                text = extract_best_text(page)
                if not text:
                    try:
                        text = clean_text(page.locator("body").inner_text(timeout=5000))
                    except Exception:
                        text = ""
                # JS-rendered sites sometimes inject their own schema.org JobPosting JSON-LD
                # client-side (not present in the raw HTML the plain fetcher sees). Safe to use —
                # it's the page's own structured data for this job, not sidebar/related-jobs noise.
                rendered_html = None
                try:
                    rendered_html = page.content()
                    jobposting = extract_jsonld_jobposting(rendered_html)
                except Exception:
                    jobposting = None
                jobposting = jobposting or {}
                meta = {
                    "title": title, "company": company, "source": "playwright/html",
                    "method": "playwright",
                    "location": jobposting.get("location"),
                    "working_location": jobposting.get("location"),
                    "employment_type": jobposting.get("employment_type"),
                    "compensation": jobposting.get("compensation"),
                    "compensation_raw": jobposting.get("compensation"),
                    "location_raw": jobposting.get("location"),
                    "apply_url": url,
                    "posted_date": jobposting.get("posted_date"),
                    "updated_date": jobposting.get("updated_date"),
                    # Structured only when the rendered page carried a JSON-LD JobPosting;
                    # otherwise a missing field is capture_failed, not not_posted.
                    "structured_source": bool(jobposting),
                    # Structured identity when the rendered page published it — preferred
                    # over the scraped page title/company by
                    # prep_common.normalize_capture_identity.
                    "jsonld_identity": ({"hiring_organization": jobposting.get("hiring_organization"),
                                         "title": jobposting.get("title")}
                                        if (jobposting.get("hiring_organization") or jobposting.get("title"))
                                        else None),
                    "comp_expected": False,
                    "location_expected": bool(jobposting.get("location")),
                    # Rendered HTML kept transiently for embedded-Greenhouse recovery.
                    "raw_html": rendered_html,
                    "questions": [],
                }
                # An ATS with no job API (Homerun) lands here, not in the ATS branch,
                # but its questions are still on a renderable apply page.
                questions = []
                ats_kind = detect_apply_ats(url)
                if ats_kind:
                    try:
                        questions = render_apply_questions(browser, url, None, ats_kind) or []
                    except Exception as exc:
                        print(f"  ! {ats_kind} question render failed for {url}: "
                              f"{type(exc).__name__}: {exc}")
                        questions = []
                    meta["questions"] = questions
                return {"ok": True, "title": title, "company": company, "body": text,
                        "method": "playwright", "error": None, "meta": meta,
                        "questions": questions}
            finally:
                page.close()
        except Exception as e:
            return {"ok": False, "title": None, "company": None, "body": "",
                    "method": "playwright", "error": f"{type(e).__name__}: {e}",
                    "meta": {}, "questions": []}
    return fetch_one


def read_urls(input_file: Path) -> list[str]:
    return [
        line.strip()
        for line in input_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def main() -> None:
    """DEPRECATED entry point — the canonical CLI is prep.py. This wrapper forwards
    to it with `--engine playwright`. The module itself remains the RENDERED-PAGE
    ENGINE (`make_fetch_one`, `render_apply_questions`) that prep.py composes."""
    print("NOTE: prep_job_urls_playwright.py is a deprecated entry point — use\n"
          "  python ENGINE__PUBLIC_GIT_TRACKED/02-PREP/prep.py <batch_dir> --engine playwright\n"
          "Forwarding with --engine playwright...")
    import sys as _sys
    import prep as prep_cli
    raise SystemExit(prep_cli.main(["prep.py"] + _sys.argv[1:] + ["--engine", "playwright"]))


if __name__ == "__main__":
    main()
