#!/usr/bin/env python3
"""Primary job-post fetcher: ATS API first, then a plain requests + extraction
fall-through. The dedupe / classify / quarantine / manifest / report logic lives
in prep_common.process_urls(); this file only knows how to FETCH one URL.

    python prep_job_urls.py "<source folder>" --input "<urls.txt>" [--force]

A plain re-run is manifest-aware: it skips URLs already fetched as usable and
retries the thin/failed ones. --force refetches everything.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup

import prep_common
from ats_fetchers import ats_company_from_url, fetch_via_ats

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


def fetch_html(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def extract_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)
    return "Unknown Title"


def extract_clean_text(html: str, url: str) -> str:
    extracted = trafilatura.extract(
        html, url=url, include_links=True, include_tables=True,
        favor_precision=True, output_format="txt",
    )
    if extracted and extracted.strip():
        return extracted.strip()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def detect_company(url: str, title: str) -> str:
    ats_company = ats_company_from_url(url)
    if ats_company:
        return ats_company
    hostname = urlparse(url).netloc.lower().replace("www.", "")
    host_parts = hostname.split(".")
    host_guess = host_parts[-2] if len(host_parts) >= 2 else hostname
    title_parts = [p.strip() for p in re.split(r"\||-|•", title) if p.strip()]
    for part in reversed(title_parts):
        if len(part.split()) <= 5 and not re.search(r"job|career|apply", part, re.I):
            return part
    return host_guess.title()


def fetch_one(url: str) -> dict:
    """Return prep_common's fetch contract for one URL."""
    try:
        ats = fetch_via_ats(url)
        if ats:
            return {"ok": True, "title": ats["title"], "company": ats["company"],
                    "body": ats["text"], "method": "ats", "error": None}
        html = fetch_html(url)
        title = extract_title(html)
        company = detect_company(url, title)
        body = extract_clean_text(html, url)
        return {"ok": True, "title": title, "company": company, "body": body,
                "method": "requests", "error": None}
    except Exception as e:
        return {"ok": False, "title": None, "company": None, "body": "",
                "method": "requests", "error": f"{type(e).__name__}: {e}"}


def read_urls(input_file: Path) -> list[str]:
    return [
        line.strip()
        for line in input_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch job URLs (ATS API first, then requests) into a batch, with "
                    "dedupe, thin/failed quarantine, a manifest and a prep report."
    )
    parser.add_argument("batch_dir", help="The 'All Job Posts (full text)' source folder for the batch")
    parser.add_argument("--input", default="job_urls.txt",
                        help="URL list: a bare filename inside batch_dir, or a path")
    parser.add_argument("--force", action="store_true",
                        help="Refetch every URL (default re-run skips already-usable, retries thin/failed)")
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

    print(f"Found {len(urls)} URL(s). Fetching (ATS API first, then requests)...")
    prep_common.process_urls(urls, batch_dir, fetch_one, force=args.force)


if __name__ == "__main__":
    main()
