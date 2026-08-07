#!/usr/bin/env python3
"""prep.py — THE canonical prep CLI (B4, 2026-07-30).

One entry point, one fetch composition, one downstream path. The two historical
CLIs (`prep_job_urls.py`, `prep_job_urls_playwright.py`) remain as ENGINE MODULES
(their `fetch_one` implementations) plus thin deprecation wrappers — separately
evolved entry points are how an enrichment once shipped in one path and not the
other (see the 43aab1e changelog lesson).

    python ENGINE__PUBLIC_GIT_TRACKED/02-PREP/prep.py "<source folder>" \\
        --input "<urls.txt>" [--force] [--engine auto|requests|playwright]

Engines:
  auto (default)  requests-first, with a per-URL Playwright fallback through
                  process_urls' existing HARD-RULE cascade (never quarantine after
                  one method), and the always-on apply-page question render for the
                  ATSes whose APIs carry no questions. Degrades to requests-only
                  (with the limitation recorded) when Playwright is not installed.
  requests        the requests engine only — deterministic, no browser at all
                  (no fallback, no apply-page render).
  playwright      the rendered-page engine only, for stubborn JS-rendered pages.

Whatever the engine, every capture flows through the SAME `process_urls` — identity
normalization, employer-name enrichment, registry, QA gate — pinned by the engine
divergence-guard tests.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ats_fetchers  # noqa: E402
import prep_common  # noqa: E402
import prep_job_urls as requests_engine  # noqa: E402

ENGINES = ("auto", "requests", "playwright")


def _have_playwright() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def build_fetchers(engine: str, browser=None):
    """The fetch composition for one engine, as
    (fetch_one, fetch_fallback, fallback_label, banner). `browser` is required for
    the playwright engine and for auto-with-playwright; injectable for tests."""
    if engine == "requests":
        return (requests_engine.fetch_one, None, None,
                "Fetching (ATS API first, then requests; --engine requests: no "
                "browser, no second-method retry)...")
    import prep_job_urls_playwright as playwright_engine
    if engine == "playwright":
        return (playwright_engine.make_fetch_one(browser), None, None,
                "Rendering with Playwright (ATS API first)...")
    # auto (with playwright available; the caller handles the degraded case)
    def apply_renderer(u, apply_hint=None):
        return playwright_engine.render_apply_questions(browser, u, apply_hint)

    def primary(u):
        return requests_engine.fetch_one(u, question_renderer=apply_renderer)

    return (primary, playwright_engine.make_fetch_one(browser), "playwright",
            "Fetching (ATS API first, then requests; apply-page questions always "
            "rendered for Ashby/Lever/Workable/Homerun; Playwright auto-retry "
            "enabled for thin/failed results)...")


def run(batch_dir, input_file, *, force: bool = False, engine: str = "auto") -> dict:
    urls = requests_engine.read_urls(Path(input_file))
    if not urls:
        raise SystemExit("No URLs found in input file.")
    if engine not in ENGINES:
        raise SystemExit(f"Unknown --engine {engine!r} (choose from {', '.join(ENGINES)})")

    if engine == "auto" and not _have_playwright():
        print(f"Found {len(urls)} URL(s). Fetching (ATS API first, then requests)... "
              f"[Playwright not installed — no automatic second-method retry available; "
              f"thin/failed results will note this limitation]")
        return prep_common.process_urls(urls, batch_dir, requests_engine.fetch_one,
                                        force=force)
    if engine == "requests":
        fetch_one, fallback, label, banner = build_fetchers("requests")
        print(f"Found {len(urls)} URL(s). {banner}")
        return prep_common.process_urls(urls, batch_dir, fetch_one, force=force)

    if engine == "playwright" and not _have_playwright():
        raise SystemExit("--engine playwright requires Playwright "
                         "(pip install -r requirements.txt, then `playwright install chromium`).")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Lend the browser to the ATS layer: its recovery paths sometimes have to render a
        # JS-shell careers page (e.g. reading the Ashby org slug out of an embed script),
        # and Playwright's sync API cannot be re-entered from inside this context.
        ats_fetchers.set_ambient_browser(browser)
        try:
            fetch_one, fallback, label, banner = build_fetchers(engine, browser)
            print(f"Found {len(urls)} URL(s). {banner}")
            return prep_common.process_urls(urls, batch_dir, fetch_one, force=force,
                                            fetch_fallback=fallback,
                                            fallback_label=label)
        finally:
            browser.close()


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Fetch job URLs into clean captures (dedupe, quarantine, QA gate, "
                    "prep report). The one canonical prep entry point.")
    parser.add_argument("batch_dir",
                        help="The 'All Job Posts (full text)' source folder for the batch")
    parser.add_argument("--input", default="job_urls.txt",
                        help="URL list: a bare filename inside batch_dir, or a path")
    parser.add_argument("--force", action="store_true",
                        help="Refetch every URL (default re-run skips already-usable, "
                             "retries thin/failed)")
    parser.add_argument("--engine", default="auto", choices=ENGINES,
                        help="auto = requests-first with per-URL Playwright fallback "
                             "(default); requests = no browser; playwright = rendered "
                             "pages only")
    return parser.parse_args(argv[1:])


def main(argv=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv)
    batch_dir = Path(args.batch_dir).expanduser().resolve()
    inp = Path(args.input).expanduser()
    input_file = inp.resolve() if (inp.is_absolute() or "/" in args.input) \
        else (batch_dir / args.input)
    if not batch_dir.exists():
        raise SystemExit(f"Source folder does not exist: {batch_dir}")
    if not input_file.exists():
        raise SystemExit(f"URL input file not found: {input_file}")
    run(batch_dir, input_file, force=args.force, engine=args.engine)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
