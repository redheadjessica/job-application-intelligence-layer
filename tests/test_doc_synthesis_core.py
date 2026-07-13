import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from doc_synthesis_core import (  # noqa: E402
    Heading,
    get_processed_commit,
    meaningful_changed_files,
    normalize_changelog,
    parse_heading,
    set_processed_commit,
)

PREAMBLE = """# JAIL Changelog

Readable project memory.

---"""


class ParseHeadingTests(unittest.TestCase):
    def test_single_date(self):
        self.assertEqual(
            parse_heading("## 2026-06-04 — One day"),
            Heading(kind="dated", start_date="2026-06-04", end_date="2026-06-04", title="One day"),
        )

    def test_same_month_range(self):
        self.assertEqual(
            parse_heading("## 2026-06-04 to 05 — Two days"),
            Heading(kind="dated", start_date="2026-06-04", end_date="2026-06-05", title="Two days"),
        )

    def test_cross_month_range(self):
        self.assertEqual(
            parse_heading("## 2026-05-18 to 2026-06-04 — Long thread"),
            Heading(kind="dated", start_date="2026-05-18", end_date="2026-06-04", title="Long thread"),
        )

    def test_rejects_backwards_range(self):
        with self.assertRaisesRegex(ValueError, "ends before it starts"):
            parse_heading("## 2026-06-05 to 04 — Backwards")


class NormalizeChangelogTests(unittest.TestCase):
    def test_sorts_by_thread_end_and_keeps_distinct_same_day_entries(self):
        markdown = f"""{PREAMBLE}

## 2026-05-22 — First same-day story

- One

## 2026-05-18 to 2026-06-04 — Long-running story

- Two

## 2026-05-22 — Second same-day story

- Three

## Pre-2026-03-08 — Exploration

- Four

## Earlier — Design

- Five
"""
        output = normalize_changelog(markdown)
        self.assertLess(output.index("Long-running story"), output.index("First same-day story"))
        self.assertLess(output.index("First same-day story"), output.index("Second same-day story"))

    def test_pins_pre_history_and_earlier_last(self):
        markdown = f"""{PREAMBLE}

## Earlier — Design

- Oldest

## 2026-04-01 — Newer

- Newer

## Pre-2026-03-08 — Exploration

- Exploring
"""
        output = normalize_changelog(markdown)
        headings = [line for line in output.splitlines() if line.startswith("## ")]
        self.assertEqual(headings[-2:], ["## Pre-2026-03-08 — Exploration", "## Earlier — Design"])

    def test_is_idempotent(self):
        markdown = f"""{PREAMBLE}

## 2026-03-08 — Foundation

- Started

## Pre-2026-03-08 — Exploration

- Exploring

## Earlier — Design

- Oldest
"""
        once = normalize_changelog(markdown)
        self.assertEqual(normalize_changelog(once), once)

    def test_requires_exactly_one_pre_history_and_earlier_section(self):
        markdown = f"""{PREAMBLE}

## 2026-03-08 — Foundation

- Started
"""
        with self.assertRaisesRegex(ValueError, "exactly one"):
            normalize_changelog(markdown)

    def test_rejects_unsupported_heading(self):
        markdown = f"""{PREAMBLE}

## Not a real heading

- Nope

## Pre-2026-03-08 — Exploration

- Exploring

## Earlier — Design

- Oldest
"""
        with self.assertRaisesRegex(ValueError, "Unsupported changelog heading"):
            normalize_changelog(markdown)


class ProcessedCommitMarkerTests(unittest.TestCase):
    def test_adds_and_updates_marker(self):
        markdown = f"""{PREAMBLE}

## 2026-03-08 — Foundation

- Started
"""
        added = set_processed_commit(markdown, "abcdef1234567890")
        self.assertEqual(get_processed_commit(added), "abcdef1234567890")

        updated = set_processed_commit(added, "1234567abcdef")
        self.assertEqual(get_processed_commit(updated), "1234567abcdef")
        self.assertEqual(updated.count("changelog-processed-through"), 1)


class MeaningfulChangedFilesTests(unittest.TestCase):
    def test_ignores_synthesis_only_files(self):
        self.assertEqual(
            meaningful_changed_files(
                ["docs/changelog.md", "scripts/doc_synthesis.py", "ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/new_batch.py"]
            ),
            ["ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/new_batch.py"],
        )

    def test_synthesis_only_commit_does_not_trigger_itself(self):
        self.assertEqual(
            meaningful_changed_files(
                [
                    "scripts/doc_synthesis.py",
                    "scripts/doc_synthesis_core.py",
                    "tests/test_doc_synthesis_core.py",
                    "scripts/README.md",
                    "docs/changelog.md",
                    "docs/doc-status.md",
                    "requirements.txt",
                ]
            ),
            [],
        )

    def test_ordinary_dependency_change_is_meaningful_alone(self):
        self.assertEqual(meaningful_changed_files(["requirements.txt"]), ["requirements.txt"])

    def test_mixed_maintenance_and_product_work_keeps_the_product_work(self):
        self.assertEqual(
            meaningful_changed_files(
                [
                    "scripts/doc_synthesis.py",
                    "requirements.txt",
                    "docs/changelog.md",
                    "ENGINE__PUBLIC_GIT_TRACKED/02-PREP/prep_job_urls.py",
                    "docs/v2-end-to-end-workflow.md",
                ]
            ),
            ["ENGINE__PUBLIC_GIT_TRACKED/02-PREP/prep_job_urls.py", "docs/v2-end-to-end-workflow.md"],
        )


if __name__ == "__main__":
    unittest.main()
