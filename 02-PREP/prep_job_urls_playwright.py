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
from ats_fetchers import ats_company_from_url, fetch_via_ats

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


def best_company_from_title(title: str, fallback: str) -> str:
    parts = [p.strip() for p in re.split(r"\||•|-", title) if p.strip()]
    bad = {"careers", "jobs", "job opportunity", "job"}
    for part in reversed(parts):
        if part.lower() not in bad and len(part) <= 60:
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


def make_fetch_one(browser):
    def fetch_one(url: str) -> dict:
        try:
            ats = fetch_via_ats(url)
            if ats:
                return {"ok": True, "title": ats["title"], "company": ats["company"],
                        "body": ats["text"], "method": "ats", "error": None}
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
                return {"ok": True, "title": title, "company": company, "body": text,
                        "method": "playwright", "error": None}
            finally:
                page.close()
        except Exception as e:
            return {"ok": False, "title": None, "company": None, "body": "",
                    "method": "playwright", "error": f"{type(e).__name__}: {e}"}
    return fetch_one


def read_urls(input_file: Path) -> list[str]:
    return [
        line.strip()
        for line in input_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Render job URLs with Playwright (deeper fallback/retry).")
    parser.add_argument("batch_dir", help="The 'All Job Posts (full text)' source folder for the batch")
    parser.add_argument("--input", default="job_urls.txt", help="URL list filename inside batch_dir, or a path")
    parser.add_argument("--force", action="store_true", help="Refetch every URL (default retries only thin/failed)")
    args = parser.parse_args()

    batch_dir = Path(args.batch_dir).expanduser().resolve()
    inp = Path(args.input).expanduser()
    input_file = inp.resolve() if (inp.is_absolute() or "/" in args.input) else (batch_dir / args.input)

    if not batch_dir.exists():
        raise SystemExit(f"Source folder does not exist: {batch_dir}")
    if not input_file.exists():
        raise SystemExit(f"URL input file not found: {input_file}")

    urls = read_urls(input_file)
    if not urls:
        raise SystemExit("No URLs found in input file.")

    print(f"Found {len(urls)} URL(s). Rendering with Playwright (ATS API first)...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            prep_common.process_urls(urls, batch_dir, make_fetch_one(browser), force=args.force)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
