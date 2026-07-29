"""Output-contract regression tests (authoritative spec, 2026-07-29).

These are PERMANENT regression fixtures: the Working Location matrix below is the
spec's own minimum test set, asserted BOTH at the normalizer level AND at the final
artifact — a real XLSX is built and the actual written cell fill hex is read back
with openpyxl (spec: "test the actual written spreadsheet cell").
"""
import csv
import json

import pytest
from openpyxl import load_workbook

import make_rankings_xlsx
import norm_contracts
from norm_contracts import (
    WL_GREEN, WL_ORANGE, WL_RED, WL_YELLOW,
    normalize_working_location, working_location_color,
)

# A generic candidate config mirroring the jail.config.json shape: home metro is NYC
# (via home_metro_aliases); SF is in city_priority but is NOT a home metro.
CFG = {
    "comp": {"currency": "USD", "target_base": 200, "floor_base": 180},
    "location": {
        "home_metro": "New York City",
        "home_metro_aliases": ["NYC", "New York", "NYC metro", "Brooklyn", "Manhattan"],
        "city_priority": ["NYC", "SF"],
    },
}


def quiet(_msg):  # suppress expected repair warnings in test output
    pass


# --------------------------------------------------------------------------- #
# Working Location — the spec's 18-case matrix (normalized text AND exact hex)
# --------------------------------------------------------------------------- #
WL_MATRIX = [
    # (input, expected canonical, expected hex)
    ("Remote", "Remote", WL_GREEN),
    ("Remote (US)", "Remote (US)", WL_GREEN),
    ("Remote or IRL NYC - 2 days", "Remote or IRL NYC - 2 days", WL_GREEN),
    ("Remote or IRL SF - 3 days", "Remote or IRL SF - 3 days", WL_GREEN),
    ("IRL NYC - 1 day", "IRL NYC - 1 day", WL_YELLOW),
    ("IRL NYC - 2 days", "IRL NYC - 2 days", WL_YELLOW),
    ("IRL NYC - 3 days", "IRL NYC - 3 days", WL_YELLOW),
    ("IRL NYC/SF - 3 days", "IRL NYC/SF - 3 days", WL_YELLOW),
    ("IRL NYC - 3 days (Mon/Wed/Thu)", "IRL NYC - 3 days (Mon/Wed/Thu)", WL_YELLOW),
    ("IRL NYC - 3+ days", "IRL NYC - 3+ days", WL_ORANGE),
    ("IRL NYC - at least 3 days", "IRL NYC - 3+ days", WL_ORANGE),
    ("IRL NYC - 4 days", "IRL NYC - 4 days", WL_ORANGE),
    ("IRL NYC - 5 days", "IRL NYC - 5 days", WL_ORANGE),
    ("IRL NYC - unknown days", "IRL NYC - unknown days", WL_ORANGE),
    ("Unknown", "Unknown", WL_ORANGE),
    # In-person outside the home geography, no remote/home-metro option -> red.
    ("IRL SF - 3 days", "IRL SF - 3 days", WL_RED),
    # The mechanical-repair case that motivated this module: missing "IRL " prefix.
    ("NYC/SF - 3 days", "IRL NYC/SF - 3 days", WL_YELLOW),
    # Bare "<City> hybrid" phrasing repairs to known-city-unknown-cadence.
    ("New York hybrid", "IRL NYC - unknown days", WL_ORANGE),
]


@pytest.mark.parametrize("raw,canonical,hexcode", WL_MATRIX)
def test_working_location_matrix(raw, canonical, hexcode):
    got = normalize_working_location(raw, CFG, warn=quiet)
    assert got == canonical
    assert working_location_color(got, CFG) == hexcode


def test_color_set_is_exactly_the_four_spec_hexes_no_grey():
    seen = {working_location_color(normalize_working_location(raw, CFG, warn=quiet), CFG)
            for raw, _, _ in WL_MATRIX}
    assert seen == {WL_GREEN, WL_YELLOW, WL_ORANGE, WL_RED}
    assert (WL_GREEN, WL_YELLOW, WL_ORANGE, WL_RED) == ("42FF35", "FDFF43", "FA9C31", "F82C1F")


def test_question_derived_location_normalizes_identically_to_jd_derived():
    """A location requirement extracted from an application question must normalize
    + color exactly like the same requirement stated in the JD."""
    jd = normalize_working_location("Hybrid — New York, NY (at least 2 days per week)", CFG, warn=quiet)
    question = normalize_working_location("NYC office - at least 2 days per week", CFG, warn=quiet)
    assert jd == question == "IRL NYC - 2+ days"
    assert working_location_color(jd, CFG) == working_location_color(question, CFG) == WL_ORANGE


def test_three_days_is_not_three_plus_days():
    assert working_location_color("IRL NYC - 3 days", CFG) == WL_YELLOW
    assert working_location_color("IRL NYC - 3+ days", CFG) == WL_ORANGE


def test_onsite_city_without_fulltime_is_unknown_days():
    assert normalize_working_location("Onsite SF", CFG, warn=quiet) == "IRL SF - unknown days"
    assert normalize_working_location("Onsite SF, full-time in office", CFG, warn=quiet) == "IRL SF - 5 days"


def test_remote_friendly_is_not_remote():
    got = normalize_working_location("NYC - 3 days, remote-friendly", CFG, warn=quiet)
    assert got == "IRL NYC - 3 days"
    assert working_location_color(got, CFG) == WL_YELLOW


def test_unparseable_becomes_unknown_with_loud_warning():
    warnings = []
    got = normalize_working_location("see posting for details", CFG, warn=warnings.append)
    assert got == "Unknown"
    assert warnings, "an unparseable value must warn, never repair silently"


def test_no_home_metro_configured_cannot_judge_geography_orange_not_red():
    assert working_location_color("IRL SF - 3 days", {}) == WL_ORANGE


# --------------------------------------------------------------------------- #
# CSV CLI pass
# --------------------------------------------------------------------------- #
HEADERS = [
    "Applied Date? [You Fill In]", "Status? [You Change]", "Lane", "Company",
    "Job Post Title + Link", "Working Location", "Comp Range",
    "Have Intro? [You Add]", "Your Notes? [You Add]", "Decline/Down Date? [You Add]",
    "FINAL Weighted Score", "How They May See Your Profile", "Your Desire Score",
    "Culture Fit", "Comp + Lifestyle Fit",
    "Mission Fit Notes", "Scope Fit Notes", "Top Reasons Notes", "Top Concerns",
    "Job File", "Base Resume Used", "Lane Fit", "Location Fit", "Comp Fit",
    "Data Completeness", "Cover Letter?",
]


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        for r in rows:
            w.writerow(r)


def make_row(company="Acme", location="Remote", comp="190-210", lane="Health - Mental Health",
             lane_fit="Mental Health (high)", loc_fit="Remote", comp_fit="Meets/above target",
             status="Apply ASAP: High Prio"):
    return [
        "", status, lane, company, f"Senior PM | https://example.com/{company.lower()}",
        location, comp, "", "", "",
        "80", "80", "80", "80", "80",
        "m", "s", "r", "c",
        f"{company.lower()}.txt", "", lane_fit, loc_fit, comp_fit, "✓ complete", "",
    ]


def test_cli_normalizes_csv_in_place_and_reports_repairs(tmp_path, capsys):
    csv_path = tmp_path / "b-rankings.csv"
    write_csv(csv_path, [
        make_row(company="RepairMe", location="NYC/SF - 3 days"),
        make_row(company="FineAlready", location="Remote"),
    ])
    changed = norm_contracts.normalize_rankings_csv(str(csv_path), CFG)
    out = capsys.readouterr().out
    assert changed == 1
    assert "RepairMe" in out and "'NYC/SF - 3 days'" in out and "'IRL NYC/SF - 3 days'" in out
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    i = HEADERS.index("Working Location")
    assert rows[1][i] == "IRL NYC/SF - 3 days"
    assert rows[2][i] == "Remote"


# --------------------------------------------------------------------------- #
# End-to-end: build a real XLSX and read the ACTUAL written cell fills back
# --------------------------------------------------------------------------- #
def cell_hex(cell):
    rgb = cell.fill.start_color.rgb
    return str(rgb)[-6:] if rgb else None


def test_xlsx_written_cells_carry_the_exact_spec_hexes(tmp_path):
    cfg_path = tmp_path / "jail.config.json"
    cfg_path.write_text(json.dumps(CFG), encoding="utf-8")
    csv_path = tmp_path / "batch-rankings.csv"
    xlsx_path = tmp_path / "batch-rankings.xlsx"
    cases = [
        ("Remote", WL_GREEN),
        ("IRL NYC - 3 days", WL_YELLOW),
        ("NYC/SF - 3 days", WL_YELLOW),        # repaired on read -> IRL NYC/SF - 3 days
        ("IRL NYC - 3+ days", WL_ORANGE),
        ("Unknown", WL_ORANGE),
        ("IRL SF - 3 days", WL_RED),
    ]
    write_csv(csv_path, [make_row(company=f"Co{i}", location=loc) for i, (loc, _) in enumerate(cases)])
    make_rankings_xlsx.build(str(csv_path), str(xlsx_path), config_path=str(cfg_path))

    wb = load_workbook(str(xlsx_path))
    ws = wb["Job Rankings"]
    headers = [c.value for c in ws[1]]
    wl_col = headers.index("Working Location") + 1
    lf_col = headers.index("Location Fit") + 1
    for i, (loc, expected) in enumerate(cases):
        r = i + 2
        assert cell_hex(ws.cell(r, wl_col)) == expected, f"Working Location fill for {loc!r}"
        assert cell_hex(ws.cell(r, lf_col)) == expected, f"Location Fit fill for {loc!r}"
        # black text, no white-font override on these cells
        color = ws.cell(r, wl_col).font.color
        assert color is None or str(color.rgb).endswith("000000")
    # the repaired cell's TEXT is canonical in the written spreadsheet too
    assert ws.cell(4, wl_col).value == "IRL NYC/SF - 3 days"
    # no grey anywhere in the populated Working Location column
    greys = {cell_hex(ws.cell(i + 2, wl_col)) for i in range(len(cases))}
    assert "D9D9D9" not in greys
