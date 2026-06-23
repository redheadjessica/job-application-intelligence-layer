#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup

from ats_fetchers import ats_company_from_url, fetch_via_ats


def slugify(text: str, max_len: int = 80) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len] or "job"


def fetch_html(url: str, timeout: int = 20) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def extract_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        return og_title["content"].strip()

    if soup.title and soup.title.string:
        return soup.title.string.strip()

    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)

    return "Unknown Title"


def extract_clean_text(html: str, url: str) -> str:
    # Best-effort main-content extraction
    extracted = trafilatura.extract(
        html,
        url=url,
        include_links=True,
        include_tables=True,
        favor_precision=True,
        output_format="txt",
    )
    if extracted and extracted.strip():
        return extracted.strip()

    # Fallback: dump visible text
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def detect_company(url: str, title: str) -> str:
    # If the URL is an ATS (greenhouse, lever, ashby, ...), the company is the org
    # slug in the path, not the host (which would yield "Greenhouse", "Lever", etc.).
    ats_company = ats_company_from_url(url)
    if ats_company:
        return ats_company

    hostname = urlparse(url).netloc.lower().replace("www.", "")
    host_parts = hostname.split(".")
    host_guess = host_parts[-2] if len(host_parts) >= 2 else hostname

    title_parts = [p.strip() for p in re.split(r"\||-|\u2022", title) if p.strip()]
    for part in reversed(title_parts):
        # If a likely company-looking piece exists in the title, use it
        if len(part.split()) <= 5 and not re.search(r"job|career|apply", part, re.I):
            return part

    return host_guess.title()


def build_output_text(url: str, title: str, company: str, body_text: str) -> str:
    return (
        f"URL: {url}\n"
        f"Page Title: {title}\n"
        f"Company: {company}\n\n"
        f"--- JOB TEXT START ---\n\n"
        f"{body_text}\n\n"
        f"--- JOB TEXT END ---\n"
    )


def process_url(url: str, output_dir: Path) -> Path:
    # Prefer a structured ATS API (e.g. Ashby) when the URL is recognized — these
    # pages render their text client-side, so a plain HTML GET returns an empty
    # shell. Fall back to HTML fetching + extraction for everything else.
    ats = fetch_via_ats(url)
    if ats:
        title = ats["title"]
        company = ats["company"]
        body_text = ats["text"]
    else:
        html = fetch_html(url)
        title = extract_title(html)
        company = detect_company(url, title)
        body_text = extract_clean_text(html, url)

    # Try to preserve role signal in filename
    first_line = title.split("|")[0].split(" - ")[0].strip()
    filename = f"{slugify(company)}__{slugify(first_line)}.txt"
    output_path = output_dir / filename

    output_text = build_output_text(url, title, company, body_text)
    output_path.write_text(output_text, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch job URLs and save clean text files into a batch folder."
    )
    parser.add_argument(
        "batch_dir",
        help="Path to the dated batch folder, e.g. ./03-06-26",
    )
    parser.add_argument(
        "--input",
        default="job_urls.txt",
        help="Name of the URL list file inside the batch folder (default: job_urls.txt)",
    )
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
    for i, url in enumerate(urls, start=1):
        try:
            out = process_url(url, batch_dir)
            print(f"[{i}/{len(urls)}] Saved: {out.name}")
        except Exception as e:
            print(f"[{i}/{len(urls)}] FAILED: {url}")
            print(f"  Error: {e}")


if __name__ == "__main__":
    main()