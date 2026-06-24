#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from ats_fetchers import ats_company_from_url, fetch_via_ats


def slugify(text: str, max_len: int = 80) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len] or "job"


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def detect_company_from_url(url: str) -> str:
    # If the URL is an ATS (greenhouse, lever, ashby, ...), the company is the org
    # slug in the path, not the host (which would yield "Greenhouse", "Lever", etc.).
    ats_company = ats_company_from_url(url)
    if ats_company:
        return ats_company

    host = urlparse(url).netloc.lower().replace("www.", "")
    parts = host.split(".")
    if len(parts) >= 2:
        company = parts[-2]
    else:
        company = host

    # basic formatting
    company = company.replace("-", " ")
    return company.title()


def best_company_from_title(title: str, fallback: str) -> str:
    parts = [p.strip() for p in re.split(r"\||•|-", title) if p.strip()]
    bad = {"careers", "jobs", "job opportunity", "job"}
    for part in reversed(parts):
        low = part.lower()
        if low not in bad and len(part) <= 60:
            return part
    return fallback


def build_output_text(url: str, title: str, company: str, body_text: str) -> str:
    return (
        f"URL: {url}\n"
        f"Page Title: {title}\n"
        f"Company: {company}\n\n"
        f"--- JOB TEXT START ---\n\n"
        f"{body_text}\n\n"
        f"--- JOB TEXT END ---\n"
    )


LIKELY_SELECTORS = [
    "main",
    "article",
    "[data-testid*='job']",
    "[class*='job-description']",
    "[class*='jobDescription']",
    "[class*='description']",
    "[class*='posting']",
    "[class*='content']",
    "[class*='careers']",
    "[id*='job-description']",
    "[id*='description']",
    "[id*='content']",
]


def extract_best_text(page) -> str:
    candidates = []

    for selector in LIKELY_SELECTORS:
        try:
            elements = page.locator(selector).all()
            for el in elements[:8]:
                try:
                    text = clean_text(el.inner_text(timeout=2000))
                    if len(text) >= 500:
                        candidates.append((len(text), selector, text))
                except Exception:
                    pass
        except Exception:
            pass

    try:
        full_main = clean_text(page.locator("body").inner_text(timeout=3000))
        if len(full_main) >= 500:
            candidates.append((len(full_main), "body", full_main))
    except Exception:
        pass

    if not candidates:
        return ""

    # Prefer longer chunks, but penalize raw body a bit if other real containers exist
    candidates.sort(key=lambda x: (x[0] - (500 if x[1] == "body" else 0)), reverse=True)
    return candidates[0][2]


def process_url(url: str, output_dir: Path, browser) -> Path:
    # Fast path: if this is a recognized ATS (e.g. Ashby) pull the job straight
    # from its JSON API. No browser render needed, and it is far more reliable
    # than matching CSS selectors against a client-rendered page.
    ats = fetch_via_ats(url)
    if ats:
        first_line = ats["title"].split("|")[0].strip()
        filename = f"{slugify(ats['company'])}__{slugify(first_line)}.txt"
        output_path = output_dir / filename
        output_path.write_text(
            build_output_text(url, ats["title"], ats["company"], ats["text"]),
            encoding="utf-8",
        )
        return output_path

    page = browser.new_page()
    page.set_default_timeout(15000)

    try:
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except PlaywrightTimeoutError:
            pass

        title = page.title().strip() or "Unknown Title"
        company_fallback = detect_company_from_url(url)
        company = best_company_from_title(title, company_fallback)

        text = extract_best_text(page)

        if not text or len(text) < 500:
            # fallback to whole visible page text
            try:
                text = clean_text(page.locator("body").inner_text(timeout=5000))
            except Exception:
                text = ""

        first_line = title.split("|")[0].strip()
        filename = f"{slugify(company)}__{slugify(first_line)}.txt"
        output_path = output_dir / filename
        output_path.write_text(build_output_text(url, title, company, text), encoding="utf-8")
        return output_path

    finally:
        page.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch job URLs with Playwright and save clean text files.")
    parser.add_argument("batch_dir", help="Path to dated batch folder, e.g. ./03-06-26")
    parser.add_argument("--input", default="job_urls.txt", help="URL list filename inside batch folder")
    args = parser.parse_args()

    batch_dir = Path(args.batch_dir).expanduser().resolve()
    # --input may be a bare filename (looked up inside batch_dir) OR a path — absolute,
    # or containing a "/" — used as given. The path form lets the URL list live outside the
    # fetch folder (e.g. one tier up in "3 - Source Material/") while texts still land in batch_dir.
    inp = Path(args.input).expanduser()
    input_file = inp.resolve() if (inp.is_absolute() or "/" in args.input) else (batch_dir / args.input)

    if not batch_dir.exists():
        raise SystemExit(f"Batch folder does not exist: {batch_dir}")
    if not input_file.exists():
        raise SystemExit(f"URL input file not found: {input_file}")

    urls = [
        line.strip()
        for line in input_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not urls:
        raise SystemExit("No URLs found in input file.")

    print(f"Found {len(urls)} URL(s).")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for i, url in enumerate(urls, start=1):
                try:
                    out = process_url(url, batch_dir, browser)
                    print(f"[{i}/{len(urls)}] Saved: {out.name}")
                except Exception as e:
                    print(f"[{i}/{len(urls)}] FAILED: {url}")
                    print(f"  Error: {e}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()