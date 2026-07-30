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
    # --- cadence-fidelity + multi-city/detail cases (2026-07-29 defect pass) ---
    # An employer-stated RANGE keeps both endpoints; the color follows its MAXIMUM.
    ("IRL NYC - 2-3 days", "IRL NYC - 2-3 days", WL_YELLOW),
    ("IRL NYC - 4-5 days", "IRL NYC - 4-5 days", WL_ORANGE),
    # "Remote or IRL ..." keeps EVERY genuinely-available office and its trailing detail.
    ("Remote or IRL NYC/SF - unknown days (hub-office salary range; remote elsewhere in "
     "US possible at 80-100% of range)",
     "Remote or IRL NYC/SF - unknown days (hub-office salary range; remote elsewhere in "
     "US possible at 80-100% of range)", WL_GREEN),
    ("IRL NYC - 3 days (Mon/Tue/Thu)", "IRL NYC - 3 days (Mon/Tue/Thu)", WL_YELLOW),
    ("IRL NYC - 5 days (non-negotiable in-office)",
     "IRL NYC - 5 days (non-negotiable in-office)", WL_ORANGE),
    ("IRL NYC/SF - unknown days", "IRL NYC/SF - unknown days", WL_ORANGE),
    ("", "Unknown", WL_ORANGE),
    ("IRL Menlo Park, CA - unknown days", "IRL Menlo Park, CA - unknown days", WL_RED),
    ("IRL Sunnyvale/Kirkland - unknown days", "IRL Sunnyvale/Kirkland - unknown days", WL_RED),
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


@pytest.mark.parametrize("raw,expected", [
    # A range is never collapsed to an endpoint, however it is written.
    ("NYC - 2-3 days", "IRL NYC - 2-3 days"),
    ("Hybrid New York, 2-3 days per week in office", "IRL NYC - 2-3 days"),
    ("NYC — 4-5 days", "IRL NYC - 4-5 days"),
    ("NYC/SF - 2-3 days", "IRL NYC/SF - 2-3 days"),
])
def test_day_ranges_are_preserved_never_collapsed(raw, expected):
    """`2-3 days` used to normalize to `3 days` — silently rewriting a cadence the
    employer stated is information loss on a field the candidate reads."""
    assert normalize_working_location(raw, CFG, warn=quiet) == expected


def test_range_color_comes_from_the_maximum():
    assert working_location_color("IRL NYC - 2-3 days", CFG) == WL_YELLOW   # max 3 -> in band
    assert working_location_color("IRL NYC - 3-4 days", CFG) == WL_ORANGE   # max 4 -> out
    assert working_location_color("IRL NYC - 4-5 days", CFG) == WL_ORANGE
    f = norm_contracts.working_location_facts("IRL NYC - 2-3 days", CFG)
    assert f["days_range"] == (2, 3) and f["days_exact"] == 3


@pytest.mark.parametrize("raw,expected", [
    # Every genuinely-available office survives, and so does the trailing detail.
    ("Remote or IRL NYC/SF - unknown days (hub-office salary range)",
     "Remote or IRL NYC/SF - unknown days (hub-office salary range)"),
    ("Remote or NYC/SF - unknown days (hub-office salary range)",
     "Remote or IRL NYC/SF - unknown days (hub-office salary range)"),
    ("Remote or hybrid in New York, NY / San Francisco, CA (hub-office salary range)",
     "Remote or IRL NYC/SF - unknown days (hub-office salary range)"),
])
def test_remote_or_irl_keeps_every_office_and_the_trailing_detail(raw, expected):
    """This form used to drop `/SF` AND the whole parenthetical."""
    got = normalize_working_location(raw, CFG, warn=quiet)
    assert got == expected
    assert working_location_color(got, CFG) == WL_GREEN


@pytest.mark.parametrize("raw,expected", [
    # `Remote (<detail>)` is part of the canonical grammar — employer detail is kept.
    ("Remote, US (in-office 1-2x/quarter; SF office option, not required)",
     "Remote (US; in-office 1-2x/quarter; SF office option, not required)"),
    ("Remote (US) or IRL US offices - unknown days", "Remote (US)"),
    ("Remote - US only", "Remote (US only)"),
    ("Remote (states: NY, CA)", "Remote (states: NY, CA)"),
    # ...but a compound adjective is not a detail, and a scope adverb is not a city.
    ("Remote-first, home base anywhere in the US", "Remote"),
    ("Fully remote", "Remote"),
    ("Remote", "Remote"),
])
def test_remote_detail_is_preserved_but_never_invented(raw, expected):
    """Real values were being flattened to bare `Remote`, discarding the employer's country
    restriction and its office-cadence note. Separately, "Fully remote" used to mint a city
    named "Fully" (`IRL Fully - unknown days`) — a capitalized word is not a place."""
    got = normalize_working_location(raw, CFG, warn=quiet)
    assert got == expected
    assert working_location_color(got, CFG) == WL_GREEN


def test_a_parenthetical_that_only_restates_the_cadence_is_not_duplicated():
    assert normalize_working_location(
        "Hybrid — New York, NY (at least 2 days per week)", CFG, warn=quiet) == "IRL NYC - 2+ days"


def test_no_home_metro_configured_cannot_judge_geography_orange_not_red():
    assert working_location_color("IRL SF - 3 days", {}) == WL_ORANGE


# --------------------------------------------------------------------------- #
# Comp Range — format repair matrix + the APPROVED midpoint Comp Fit rule
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("190-210", "190-210"),                 # canonical passthrough
    ("??", "??"),                           # unknown passthrough
    ("$125K–$250K", "125-250"),             # $, K, en dash
    ("125,000 - 250,000", "125-250"),       # commas + full-dollar
    ("232,000-282,000", "232-282"),         # full-dollar, no spaces
    ("180", "180-180"),                     # single value -> N-N
    ("150k to 190k", "150-190"),            # "to" range
    ("", "??"),
])
def test_normalize_comp_range_repairs(raw, expected):
    assert norm_contracts.normalize_comp_range(raw, warn=quiet) == expected


def test_normalize_comp_range_garbage_warns_loudly():
    warnings = []
    assert norm_contracts.normalize_comp_range("competitive salary", warn=warnings.append) == "??"
    assert warnings
    warnings2 = []
    assert norm_contracts.normalize_comp_range("Zone A 200-250 Zone B 180-220", warn=warnings2.append) == "??"
    assert warnings2, "ambiguous multi-band text must fail loudly, not silently pick a band"


# Midpoint rule vs floor 180 / target 200 (approved 2026-07-29): red iff max < floor;
# green iff midpoint >= target; else yellow.
@pytest.mark.parametrize("comp_range,label", [
    ("125-250", "Near target"),          # midpoint 187.5 < 200 -> yellow (old rule said green)
    ("210-250", "Meets/above target"),   # midpoint 230 -> green
    ("120-170", "Below floor"),          # max 170 < 180 -> red
    ("190-210", "Meets/above target"),   # midpoint exactly 200 -> green
    ("??", "Unknown"),
    ("", "Unknown"),
])
def test_comp_fit_label_midpoint_rule(comp_range, label):
    assert norm_contracts.comp_fit_label(comp_range, CFG) == label


def test_comp_fit_label_no_comp_prefs():
    assert norm_contracts.comp_fit_label("190-210", {}) == "No comp prefs"


# --------------------------------------------------------------------------- #
# Lane — bucket taxonomy (Health / Consumer / Work / Other; NEVER "Work Tools")
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("Work Tools - Collaboration", "Work - Collaboration"),
    ("Work Tools", "Work"),
    ("work tools - Productivity", "Work - Productivity"),
    ("Work - Project Management", "Work - Project Management"),     # already canonical
    ("Health - Mental Health", "Health - Mental Health"),           # exact rule unchanged
    ("Health - Consumer Mental Health", "Health - Mental Health"),  # qualifier stripped
    ("Health-Provider Tools", "Health - Provider Tools"),           # spacing enforced
    ("Consumer - Home Sharing", "Consumer - Home Sharing"),
    ("Other - Fintech", "Other - Fintech"),
    ("Fintech Infrastructure", "Fintech Infrastructure"),           # non-bucket passthrough
])
def test_normalize_lane(raw, expected):
    assert norm_contracts.normalize_lane(raw) == expected


# --------------------------------------------------------------------------- #
# Tailored-application names — "Company - Canonical Role" (spec's required
# examples + incorrect-form repairs; company names here are generic engine
# test data, same precedent as the BetterUp prep fixtures)
# --------------------------------------------------------------------------- #
APP_NAME_MATRIX = [
    # ((company, raw role), exact required output)
    (("Asana", "Senior Product Manager, Project & Task Experience"), "Asana - Senior PM, Project & Task Experience"),
    (("ClickUp", "Senior Product Manager"), "ClickUp - Senior PM"),
    (("ClickUp", "Staff Product Manager"), "ClickUp - Staff PM"),
    # "Chief Product Officer" is NOT "Product Manager" — stays verbatim.
    (("Feeld", "Chief Product Officer"), "Feeld - Chief Product Officer"),
    (("Courier Health", "Senior Product Manager"), "Courier Health - Senior PM"),
    (("Dorsia", "Product Manager, Consumer Experience"), "Dorsia - PM, Consumer Experience"),
    # Employer " - " separator inside the title becomes the comma separator.
    (("Fetch", "Staff Product Manager - Referral, Growth"), "Fetch - Staff PM, Referral Growth"),
    (("Figma", "Product Manager, AI Growth"), "Figma - PM, AI Growth"),
    (("Findem", "Principal Product Manager"), "Findem - Principal PM"),
    (("Google", "Product Manager, Google Docs"), "Google - PM, Google Docs"),
    (("Willow Health", "Senior Product Manager, Care Delivery"), "Willow Health - Senior PM, Care Delivery"),
    # Incorrect-form repairs (the spec's listed bad forms must repair):
    (("Courier Health", "Sr Product Manager"), "Courier Health - Senior PM"),
    (("Courier Health", "Sr. Product Manager"), "Courier Health - Senior PM"),
    (("Dorsia", "PM Consumer Experience"), "Dorsia - PM, Consumer Experience"),
    (("Fetch", "Staff PM Referral Growth"), "Fetch - Staff PM, Referral Growth"),
    (("Google", "Product Manager Google Docs"), "Google - PM, Google Docs"),
    (("Willow Health", "Sr PM, Care Delivery"), "Willow Health - Senior PM, Care Delivery"),
    # Her explicit answers: Vice President -> VP; Director stays Director.
    (("Acme", "Vice President of Product"), "Acme - VP of Product"),
    (("Acme", "Director of Product"), "Acme - Director of Product"),
    # Filesystem rule: slash and colon are stripped.
    (("Acme", "PM: Growth/Retention"), "Acme - PM, Growth Retention"),
    # Preserve Staff/Principal + qualifiers verbatim.
    (("Acme", "Principal Product Manager, Platform"), "Acme - Principal PM, Platform"),
]


@pytest.mark.parametrize("inputs,expected", APP_NAME_MATRIX)
def test_canonical_application_name_matrix(inputs, expected):
    company, role = inputs
    assert norm_contracts.canonical_application_name(company, role) == expected


@pytest.mark.parametrize("inputs,expected", APP_NAME_MATRIX)
def test_canonical_application_name_is_idempotent(inputs, expected):
    """Re-running the canonicalizer on its own output changes nothing — a re-run
    of a workflow must land in the SAME folder, never a variant."""
    company, _ = inputs
    canonical_role = expected.split(" - ", 1)[1]
    assert norm_contracts.canonical_application_name(company, canonical_role) == expected


def test_never_senior_to_sr_and_existing_comma_never_removed():
    assert norm_contracts.canonical_application_role("Senior PM") == "Senior PM"
    assert norm_contracts.canonical_application_role("Senior PM, Care Delivery") == "Senior PM, Care Delivery"
    # comma insertion only ADDs the separator; it never fires when one exists
    assert "," in norm_contracts.canonical_application_role("PM, Consumer Experience")


def test_application_name_cli_prints_the_exact_string():
    """The CLI is the contract surface the agents actually call — invoke it for real."""
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path
    script = _Path(norm_contracts.__file__)
    out = subprocess.run(
        [_sys.executable, str(script), "--application-name",
         "--company", "Fetch", "--role", "Staff Product Manager - Referral, Growth"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert out == "Fetch - Staff PM, Referral Growth\n"
    out2 = subprocess.run(
        [_sys.executable, str(script), "--application-role", "--role", "Sr Product Manager"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert out2 == "Senior PM\n"


def test_application_name_survives_the_real_filesystem_layer(tmp_path):
    """mkdir with the CLI's output and assert the exact on-disk directory name —
    the final artifact is the folder, not the string."""
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path
    script = _Path(norm_contracts.__file__)
    name = subprocess.run(
        [_sys.executable, str(script), "--application-name",
         "--company", "Willow Health", "--role", "Sr PM, Care Delivery"],
        capture_output=True, text=True, check=True,
    ).stdout.rstrip("\n")
    (tmp_path / name).mkdir()
    assert [p.name for p in tmp_path.iterdir()] == ["Willow Health - Senior PM, Care Delivery"]
    # the resume-base filename uses the same string verbatim
    resume = tmp_path / name / f"Candidate-Resume - {name}.docx"
    resume.write_bytes(b"")
    assert resume.name == "Candidate-Resume - Willow Health - Senior PM, Care Delivery.docx"


# --------------------------------------------------------------------------- #
# CSV CLI pass
# --------------------------------------------------------------------------- #
HEADERS = [
    "Applied Date? [You Fill In]", "Status? [You Change]", "Lane", "Company",
    "Job Post Title + Link", "Working Location", "Comp Range", "Posted",
    "Have Intro? [You Add]", "Your Notes? [You Add]", "Decline/Down Date? [You Add]",
    "FINAL Weighted Score", "How They May See Your Profile", "Your Desire Score",
    "Culture Fit", "Comp + Lifestyle Fit", "Comp + Lifestyle Fit Notes",
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
        location, comp, "", "", "", "",
        "80", "80", "80", "80", "80",
        "Cash 26/40 (midpoint ~$188K) | Location 30/30 (fully remote) | Equity 19/20",
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


def test_cli_repairs_comp_range_and_recomputes_comp_fit(tmp_path, capsys):
    csv_path = tmp_path / "b-rankings.csv"
    write_csv(csv_path, [
        # Full-dollar comp + an optimistic legacy Comp Fit label (old high-only rule).
        make_row(company="EnvelopeCo", comp="$125,000 - $250,000", comp_fit="Meets/above target"),
    ])
    norm_contracts.normalize_rankings_csv(str(csv_path), CFG)
    capsys.readouterr()
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[1][HEADERS.index("Comp Range")] == "125-250"
    # midpoint 187.5 vs target 200 -> the CLI's re-derived midpoint label wins
    assert rows[1][HEADERS.index("Comp Fit")] == "Near target"


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


# The palette this column REPLACED. None of it may reappear in a regenerated sheet.
OLD_PALETTE = {"A9D08E", "FFE699", "F4B183", "D9D9D9", "F4A6A6"}


def test_whole_matrix_reaches_the_spreadsheet_with_the_right_fill_and_text(tmp_path):
    """The full regression matrix through the FINAL artifact: every case's Working
    Location text and the actual written fill hex of both Working Location and Location
    Fit — with zero greys and zero old-palette hexes anywhere in those two columns."""
    cfg_path = tmp_path / "jail.config.json"
    cfg_path.write_text(json.dumps(CFG), encoding="utf-8")
    csv_path = tmp_path / "matrix-rankings.csv"
    xlsx_path = tmp_path / "matrix-rankings.xlsx"
    write_csv(csv_path, [make_row(company=f"Co{i}", location=raw)
                         for i, (raw, _, _) in enumerate(WL_MATRIX)])
    make_rankings_xlsx.build(str(csv_path), str(xlsx_path), config_path=str(cfg_path))

    wb = load_workbook(str(xlsx_path))
    ws = wb["Job Rankings"]
    headers = [c.value for c in ws[1]]
    wl_col, lf_col = headers.index("Working Location") + 1, headers.index("Location Fit") + 1
    seen = {}
    for i, (raw, canonical, expected) in enumerate(WL_MATRIX):
        r = i + 2
        assert ws.cell(r, wl_col).value == canonical, f"written text for {raw!r}"
        assert cell_hex(ws.cell(r, wl_col)) == expected, f"Working Location fill for {raw!r}"
        assert cell_hex(ws.cell(r, lf_col)) == expected, f"Location Fit fill for {raw!r}"
        seen[canonical] = cell_hex(ws.cell(r, wl_col))
    assert set(seen.values()) == {WL_GREEN, WL_YELLOW, WL_ORANGE, WL_RED}
    assert not (set(seen.values()) & OLD_PALETTE)


def test_work_tools_cannot_survive_csv_to_xlsx_regeneration(tmp_path, capsys):
    """A model-emitted (or legacy-CSV) 'Work Tools' Lane value must be repaired by
    BOTH enforcement layers: the CLI pass rewrites the CSV, and the XLSX build
    re-normalizes on read — so 'Work Tools' can never reach a final artifact.
    Lane Fit is candidate data and stays byte-identical."""
    cfg_path = tmp_path / "jail.config.json"
    cfg_path.write_text(json.dumps(CFG), encoding="utf-8")
    lane_fit = "Work Tools / Collaboration / Productivity (medium)"  # user's lane NAME — untouched
    csv_path = tmp_path / "lane-rankings.csv"
    xlsx_path = tmp_path / "lane-rankings.xlsx"
    write_csv(csv_path, [
        make_row(company="ToolsCo", lane="Work Tools - Collaboration", lane_fit=lane_fit),
        make_row(company="BareCo", lane="Work Tools", lane_fit=lane_fit),
        make_row(company="MindCo", lane="Health - Mental Health", lane_fit="Mental Health (high)"),
    ])
    # Layer 1: the CLI pass (what vet-jobs.js runs) rewrites the CSV in place.
    norm_contracts.normalize_rankings_csv(str(csv_path), CFG)
    capsys.readouterr()
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    li, lfi = HEADERS.index("Lane"), HEADERS.index("Lane Fit")
    assert rows[1][li] == "Work - Collaboration"
    assert rows[2][li] == "Work"
    assert rows[3][li] == "Health - Mental Health"
    assert rows[1][lfi] == lane_fit and rows[2][lfi] == lane_fit  # Lane Fit untouched
    # Layer 2: even a CSV that DIDN'T go through the CLI regenerates clean.
    write_csv(csv_path, [make_row(company="ToolsCo", lane="Work Tools - Collaboration", lane_fit=lane_fit)])
    make_rankings_xlsx.build(str(csv_path), str(xlsx_path), config_path=str(cfg_path))
    wb = load_workbook(str(xlsx_path))
    ws = wb["Job Rankings"]
    headers = [c.value for c in ws[1]]
    assert ws.cell(2, headers.index("Lane") + 1).value == "Work - Collaboration"
    assert ws.cell(2, headers.index("Lane Fit") + 1).value == lane_fit
    for row in ws.iter_rows():
        for cell in row:
            assert cell.value != "Work Tools - Collaboration"


def test_xlsx_comp_cells_recolored_by_midpoint_rule(tmp_path):
    """Old CSVs regenerate with honest comp colors: the Comp Fit label is re-derived
    from the NORMALIZED Comp Range on read (midpoint rule), and the actual written
    Comp Range + Comp Fit cell fills reflect it (COMP_LABEL_COLORS palette kept)."""
    cfg_path = tmp_path / "jail.config.json"
    cfg_path.write_text(json.dumps(CFG), encoding="utf-8")
    csv_path = tmp_path / "comp-rankings.csv"
    xlsx_path = tmp_path / "comp-rankings.xlsx"
    GREEN, YELLOW, RED, GREY = "A9D08E", "FFE699", "F4A6A6", "D9D9D9"
    cases = [
        # (raw comp, stale legacy Comp Fit label, expected normalized, expected label, expected hex)
        ("125-250", "Meets/above target", "125-250", "Near target", YELLOW),
        ("210-250", "Near target", "210-250", "Meets/above target", GREEN),
        ("120-170", "Meets/above target", "120-170", "Below floor", RED),
        ("$190K–$210K", "Unknown", "190-210", "Meets/above target", GREEN),
        ("??", "Meets/above target", "??", "Unknown", GREY),
    ]
    write_csv(csv_path, [make_row(company=f"C{i}", comp=raw, comp_fit=stale)
                         for i, (raw, stale, _, _, _) in enumerate(cases)])
    make_rankings_xlsx.build(str(csv_path), str(xlsx_path), config_path=str(cfg_path))
    wb = load_workbook(str(xlsx_path))
    ws = wb["Job Rankings"]
    headers = [c.value for c in ws[1]]
    cr_col = headers.index("Comp Range") + 1
    cf_col = headers.index("Comp Fit") + 1
    for i, (raw, _stale, norm, label, hexcode) in enumerate(cases):
        r = i + 2
        assert ws.cell(r, cr_col).value == norm, f"Comp Range text for {raw!r}"
        assert ws.cell(r, cf_col).value == label, f"Comp Fit label for {raw!r}"
        assert cell_hex(ws.cell(r, cr_col)) == hexcode, f"Comp Range fill for {raw!r}"
        assert cell_hex(ws.cell(r, cf_col)) == hexcode, f"Comp Fit fill for {raw!r}"

# --------------------------------------------------------------------------- #
# Posted column — the EMPLOYER's publication date, read back out of the capture.
# Static ISO date by design: no age / "days open" math, which would go stale in a
# saved sheet. Filled by the same back-fill mechanism as the other contract columns,
# so regenerating an OLD rankings CSV picks the date up too.
# --------------------------------------------------------------------------- #
# The CURRENT capture layout (JOB SNAPSHOT format, 2026-07-29): `Job Posted At:` is a
# human date inside the pre-body snapshot; CAPTURE DETAILS sits below the END marker.
CAPTURE_TEMPLATE = """JOB SNAPSHOT
============
Company: {company}
Role: Senior PM
Job Posting URL: https://example.com/job/1
{posted}
Job Updated At: Unknown

WORK DETAILS
============
Employment: Full Time
Work Arrangement: Remote
Working Location(s): Remote
Office Expectation: Not Specified

--- JOB TEXT START ---
body
--- JOB TEXT END ---

CAPTURE DETAILS
---------------
Captured: July 29, 2026 at 4:06 PM ET
Application URL: https://example.com/job/1
Source: Greenhouse
Posting ATS ID: 1
Methods Checked: ATS API
Verification: Job Description ✓ | Compensation ✓ | Working Location ✓
"""

# The LEGACY layout — old batches must keep filling the Posted column without re-fetching,
# so the dual-regex path is pinned in BOTH directions.
LEGACY_CAPTURE_TEMPLATE = """URL: https://example.com/job/1
Application URL: https://example.com/job/1
Company: {company}
Role: Senior PM
Source: greenhouse-boards-api · Posting ID: 1 · Captured: 2026-07-29 · Methods tried: ats
{posted}
== NORMALIZED (for vetting) ==
Working Location: Remote   [found]

--- JOB TEXT START ---
body
--- JOB TEXT END ---
"""


def write_capture(batch_root, company, posted="Job Posted At: June 13, 2026",
                  template=CAPTURE_TEMPLATE):
    src = batch_root / "3 - Source Material" / "All Job Posts (full text)"
    src.mkdir(parents=True, exist_ok=True)
    path = src / f"{company.lower()}.txt"
    path.write_text(template.format(company=company, posted=posted), encoding="utf-8")
    return path


def write_legacy_capture(batch_root, company, posted="Posted: 2026-06-13"):
    return write_capture(batch_root, company, posted=posted, template=LEGACY_CAPTURE_TEMPLATE)


def test_posted_is_read_out_of_the_current_snapshot_line(tmp_path):
    write_capture(tmp_path, "Acme")
    rankings = tmp_path / "1 - Rankings"
    rankings.mkdir()
    assert norm_contracts.posted_date_from_capture("acme.txt", base_dir=rankings) == "2026-06-13"
    # `Unknown` / absent line / absent file -> blank, never a guess.
    write_capture(tmp_path, "NoDate", posted="Job Posted At: Unknown")
    assert norm_contracts.posted_date_from_capture("nodate.txt", base_dir=rankings) == ""
    write_capture(tmp_path, "MissingLine", posted="")
    assert norm_contracts.posted_date_from_capture("missingline.txt", base_dir=rankings) == ""
    assert norm_contracts.posted_date_from_capture("missing.txt", base_dir=rankings) == ""
    assert norm_contracts.posted_date_from_capture("", base_dir=rankings) == ""
    # An ISO value on the current line parses too (parser accepts both forms).
    write_capture(tmp_path, "IsoDate", posted="Job Posted At: 2026-06-14")
    assert norm_contracts.posted_date_from_capture("isodate.txt", base_dir=rankings) == "2026-06-14"


def test_posted_is_still_read_out_of_a_legacy_capture(tmp_path):
    """Old-format captures (provenance `Posted:` line) keep filling the rankings
    Posted column — no re-fetch needed to regenerate an old batch."""
    write_legacy_capture(tmp_path, "Acme")
    rankings = tmp_path / "1 - Rankings"
    rankings.mkdir()
    assert norm_contracts.posted_date_from_capture("acme.txt", base_dir=rankings) == "2026-06-13"
    write_legacy_capture(tmp_path, "NoDate", posted="")
    assert norm_contracts.posted_date_from_capture("nodate.txt", base_dir=rankings) == ""


def test_posted_search_is_bounded_to_the_pre_body_region(tmp_path):
    """A fake `Job Posted At:` / `Posted:` line INSIDE the job body (LinkedIn-style
    in-body metadata) must never win — only the snapshot region counts."""
    src = tmp_path / "3 - Source Material" / "All Job Posts (full text)"
    src.mkdir(parents=True, exist_ok=True)
    decoy_body = ("body text\nJob Posted At: January 1, 1999\nPosted: 1999-01-01\nmore text")
    (src / "decoy.txt").write_text(
        CAPTURE_TEMPLATE.format(company="Decoy", posted="Job Posted At: Unknown")
        .replace("body", decoy_body), encoding="utf-8")
    rankings = tmp_path / "1 - Rankings"
    rankings.mkdir()
    assert norm_contracts.posted_date_from_capture("decoy.txt", base_dir=rankings) == ""
    # Real snapshot date + in-body decoy: the snapshot line wins.
    (src / "real.txt").write_text(
        CAPTURE_TEMPLATE.format(company="Real", posted="Job Posted At: June 13, 2026")
        .replace("body", decoy_body), encoding="utf-8")
    assert norm_contracts.posted_date_from_capture("real.txt", base_dir=rankings) == "2026-06-13"
    # A hand-made capture with NO body marker still parses (whole-file fallback).
    (src / "handmade.txt").write_text("Job Posted At: June 15, 2026\npasted text",
                                      encoding="utf-8")
    assert norm_contracts.posted_date_from_capture("handmade.txt", base_dir=rankings) == "2026-06-15"


def test_updated_date_reader_accepts_both_formats(tmp_path):
    src = tmp_path / "3 - Source Material" / "All Job Posts (full text)"
    src.mkdir(parents=True, exist_ok=True)
    (src / "cur.txt").write_text(
        CAPTURE_TEMPLATE.format(company="Cur", posted="Job Posted At: June 13, 2026")
        .replace("Job Updated At: Unknown", "Job Updated At: June 20, 2026"),
        encoding="utf-8")
    (src / "leg.txt").write_text(
        LEGACY_CAPTURE_TEMPLATE.format(
            company="Leg", posted="Posted: 2026-06-13 · Updated: 2026-06-21"),
        encoding="utf-8")
    rankings = tmp_path / "1 - Rankings"
    rankings.mkdir()
    assert norm_contracts.updated_date_from_capture("cur.txt", base_dir=rankings) == "2026-06-20"
    assert norm_contracts.updated_date_from_capture("leg.txt", base_dir=rankings) == "2026-06-21"
    assert norm_contracts.updated_date_from_capture("missing.txt", base_dir=rankings) == ""


def test_human_capture_dates_parse_to_iso():
    assert norm_contracts._parse_capture_date("June 13, 2026") == "2026-06-13"
    assert norm_contracts._parse_capture_date("February 2, 2026") == "2026-02-02"
    assert norm_contracts._parse_capture_date("2026-06-13") == "2026-06-13"
    assert norm_contracts._parse_capture_date("2026-06-13T09:05:32-04:00") == "2026-06-13"
    assert norm_contracts._parse_capture_date("Unknown") == ""
    assert norm_contracts._parse_capture_date("") == ""
    assert norm_contracts._parse_capture_date("not a date") == ""


def test_status_spelling_drift_is_repaired_to_the_dropdown_value():
    """The real defect: three rows read "Apply if Time" (lowercase "if"), which is not one of the
    12 tracker values, so those cells lost their dropdown match and their lifecycle fill."""
    canon = "Apply Eventually: Apply If Time"
    for drift in ("Apply Eventually: Apply if Time",
                  "apply eventually: apply if time",
                  "  Apply Eventually:  Apply If Time  ",
                  "Apply Eventually - Apply If Time"):
        assert norm_contracts.normalize_status(drift) == canon
    # Every canonical value is a fixed point, so a repair pass can never churn a correct sheet.
    for v in norm_contracts.STATUS_VALUES:
        assert norm_contracts.normalize_status(v) == v
    # Blank stays blank; a value outside the vocabulary is warned about, never rewritten.
    assert norm_contracts.normalize_status("") == ""
    warnings = []
    assert norm_contracts.normalize_status("Ghosted after 3 rounds",
                                           warn=warnings.append) == "Ghosted after 3 rounds"
    assert warnings and "not one of" in warnings[0]


def test_cli_pass_repairs_a_drifted_status_cell(tmp_path):
    """End to end through the CSV the user actually opens: the miscased value is rewritten and the
    row's own status MEANING is untouched (this pass never reassigns a status)."""
    csv_path = tmp_path / "rankings.csv"
    write_csv(csv_path, [
        make_row(company="Acme", status="Apply Eventually: Apply if Time"),
        make_row(company="Notesco", status="Apply ASAP: High Prio"),
    ])
    norm_contracts.normalize_rankings_csv(csv_path, {}, out=lambda *_: None)
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    assert rows[0]["Status? [You Change]"] == "Apply Eventually: Apply If Time"
    assert rows[1]["Status? [You Change]"] == "Apply ASAP: High Prio"
    # Idempotent: a second pass reports nothing left to repair.
    assert norm_contracts.normalize_rankings_csv(csv_path, {}, out=lambda *_: None) == 0


def test_status_vocabulary_has_exactly_one_definition():
    """A second copy of the list is a place for the dropdown and the repair map to drift apart."""
    import make_rankings_xlsx
    assert make_rankings_xlsx.STATUS_VALUES is norm_contracts.STATUS_VALUES
    # Every value that gets a lifecycle color must be a real dropdown value, and vice versa.
    assert set(make_rankings_xlsx.STATUS_COLORS) == set(norm_contracts.STATUS_VALUES)


def test_capture_search_never_escapes_its_own_batch(tmp_path):
    """A row must never bind to a same-named capture belonging to a DIFFERENT batch. The
    last-resort filename search may step up to its own batch root, but no further."""
    reviews = tmp_path / "__READY_TO_REVIEW__"
    ours, theirs = reviews / "07-29-26", reviews / "06-02-26"
    write_capture(theirs, "Acme", posted="Job Posted At: January 1, 1999")
    ours.mkdir(parents=True)
    # base_dir is the BATCH ROOT here, so its parent is the reviews root holding every other
    # batch. Our batch has no such capture; the neighbour's must NOT be picked up.
    assert norm_contracts.posted_date_from_capture("acme.txt", base_dir=ours) == ""
    # Once it exists in OUR batch, the same lookup resolves — the bound is on breadth, not depth.
    write_capture(ours, "Acme", posted="Job Posted At: July 29, 2026")
    assert norm_contracts.posted_date_from_capture("acme.txt", base_dir=ours) == "2026-07-29"
    # And from the rankings subfolder, stepping up to the batch root is still allowed.
    rankings = ours / "1 - Rankings"
    rankings.mkdir()
    assert norm_contracts.posted_date_from_capture("acme.txt", base_dir=rankings) == "2026-07-29"


def test_cli_pass_fills_the_posted_column_from_the_captures(tmp_path):
    write_capture(tmp_path, "Acme")
    write_capture(tmp_path, "NoDate", posted="")
    rankings = tmp_path / "1 - Rankings"
    rankings.mkdir()
    csv_path = rankings / "b-rankings.csv"
    write_csv(csv_path, [make_row(company="Acme"), make_row(company="NoDate")])
    norm_contracts.normalize_rankings_csv(str(csv_path), CFG)
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    pi = HEADERS.index("Posted")
    assert rows[1][pi] == "2026-06-13"
    assert rows[2][pi] == ""          # employer published no date -> stays blank
    # It is a static date: no age/"days open" value is ever written.
    assert "days" not in rows[1][pi]


def test_a_posted_value_already_in_the_sheet_is_never_overwritten(tmp_path):
    write_capture(tmp_path, "Acme")
    rankings = tmp_path / "1 - Rankings"
    rankings.mkdir()
    csv_path = rankings / "b-rankings.csv"
    row = make_row(company="Acme")
    row[HEADERS.index("Posted")] = "2020-01-01"
    write_csv(csv_path, [row])
    norm_contracts.normalize_rankings_csv(str(csv_path), CFG)
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[1][HEADERS.index("Posted")] == "2020-01-01"


LEGACY_HEADERS = [h for h in HEADERS if h != "Posted"]


def write_legacy_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(LEGACY_HEADERS)
        for r in rows:
            w.writerow(r)


def legacy_row(**kw):
    row = make_row(**kw)
    del row[HEADERS.index("Posted")]
    return row


def test_an_old_csv_without_the_column_gets_it_inserted_and_filled(tmp_path):
    write_capture(tmp_path, "Acme")
    rankings = tmp_path / "1 - Rankings"
    rankings.mkdir()
    csv_path = rankings / "old-rankings.csv"
    write_legacy_csv(csv_path, [legacy_row(company="Acme")])
    norm_contracts.normalize_rankings_csv(str(csv_path), CFG)
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    # Inserted right after Comp Range, ahead of the editable columns; every other column
    # keeps its meaning.
    assert rows[0] == HEADERS
    assert rows[0][rows[0].index("Comp Range") + 1] == "Posted"
    assert rows[0].index("Posted") < rows[0].index("Have Intro? [You Add]")
    assert rows[1][HEADERS.index("Posted")] == "2026-06-13"
    assert rows[1][HEADERS.index("Comp Range")] == "190-210"
    assert rows[1][HEADERS.index("Job File")] == "acme.txt"


def test_posted_column_reaches_the_written_spreadsheet(tmp_path):
    write_capture(tmp_path, "Acme")
    cfg_path = tmp_path / "jail.config.json"
    cfg_path.write_text(json.dumps(CFG), encoding="utf-8")
    rankings = tmp_path / "1 - Rankings"
    rankings.mkdir()
    csv_path = rankings / "batch-rankings.csv"
    xlsx_path = rankings / "batch-rankings.xlsx"
    # A LEGACY csv (no Posted column) that never went through the CLI still regenerates
    # with the column populated — the XLSX build re-runs the same back-fill on read.
    write_legacy_csv(csv_path, [legacy_row(company="Acme")])
    make_rankings_xlsx.build(str(csv_path), str(xlsx_path), config_path=str(cfg_path))
    wb = load_workbook(str(xlsx_path))
    ws = wb["Job Rankings"]
    headers = [c.value for c in ws[1]]
    assert headers[headers.index("Comp Range") + 1] == "Posted"
    col = headers.index("Posted") + 1
    assert ws.cell(2, col).value == "2026-06-13"
    assert ws.cell(2, col).alignment.horizontal == "left"
    assert ws.column_dimensions[ws.cell(1, col).column_letter].width == 12


# --------------------------------------------------------------------------- #
# "Comp + Lifestyle Fit Notes" — the practicality dimension's prose companion.
#
# It exists because this rationale used to be written into `Comp Fit`, which is contract-owned:
# the normalization pass correctly re-derives that label from the comp range and destroyed the
# prose. These tests pin BOTH halves of the fix — the prose survives in its own column, and the
# derived label still wins in Comp Fit.
# --------------------------------------------------------------------------- #
H_PN = "Comp + Lifestyle Fit Notes"
PROSE = ("Cash 26/40 (midpoint ~$188K) | Location 30/30 (fully remote) "
         "| Equity+bonus+401k 19/20 (equity stated; bonus stated; 401k stated)")
NO_PN_HEADERS = [h for h in HEADERS if h != H_PN]


def write_no_pn_csv(path, rows):
    """A CSV from before the notes column existed (everything else current)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(NO_PN_HEADERS)
        for r in rows:
            w.writerow(r)


def no_pn_row(**kw):
    row = make_row(**kw)
    del row[HEADERS.index(H_PN)]
    return row


def by_name(header_row, data_row):
    """Header-name -> value, so assertions never depend on a column index."""
    return dict(zip(header_row, data_row))


def test_legacy_csv_gets_the_notes_column_inserted_in_position_with_nothing_shifted(tmp_path):
    csv_path = tmp_path / "old-rankings.csv"
    write_no_pn_csv(csv_path, [no_pn_row(company="Notesco", comp="190-210")])
    norm_contracts.normalize_rankings_csv(str(csv_path), CFG, out=lambda _m: None)
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    hdr = rows[0]
    assert hdr == HEADERS
    # Immediately after the score it annotates, at the head of the notes block.
    assert hdr[hdr.index("Comp + Lifestyle Fit") + 1] == H_PN
    assert hdr.index(H_PN) < hdr.index("Mission Fit Notes")
    got = by_name(hdr, rows[1])
    assert got[H_PN] == ""          # model rationale can't be re-derived — empty, not shifted data
    # Every other column keeps its OWN value (assert by name, never by index).
    assert got["Company"] == "Notesco"
    assert got["Comp Range"] == "190-210"
    assert got["Comp + Lifestyle Fit"] == "80"
    assert got["Mission Fit Notes"] == "m"
    assert got["Scope Fit Notes"] == "s"
    assert got["Top Reasons Notes"] == "r"
    assert got["Top Concerns"] == "c"
    assert got["Job File"] == "notesco.txt"
    assert got["Lane Fit"] == "Mental Health (high)"
    assert got["Comp Fit"] == "Meets/above target"
    assert got["Data Completeness"] == "✓ complete"


def test_a_relabelled_score_column_still_anchors_the_insert(tmp_path):
    # A candidate whose scoring card renamed the dimension: the static "Mission Fit Notes"
    # anchor puts the notes column in the same slot.
    renamed = ["Pay + Life" if h == "Comp + Lifestyle Fit" else h for h in NO_PN_HEADERS]
    csv_path = tmp_path / "relabelled-rankings.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(renamed)
        w.writerow(no_pn_row(company="Notesco"))
    norm_contracts.normalize_rankings_csv(str(csv_path), CFG, out=lambda _m: None)
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    hdr = rows[0]
    assert hdr[hdr.index("Pay + Life") + 1] == H_PN
    assert by_name(hdr, rows[1])["Mission Fit Notes"] == "m"


def test_a_csv_that_already_has_the_notes_column_round_trips_unchanged(tmp_path):
    csv_path = tmp_path / "b-rankings.csv"
    row = make_row(company="Notesco", comp="190-210")
    row[HEADERS.index(H_PN)] = PROSE
    write_csv(csv_path, [row])
    before = csv_path.read_text(encoding="utf-8")
    changed = norm_contracts.normalize_rankings_csv(str(csv_path), CFG, out=lambda _m: None)
    assert changed == 0
    assert csv_path.read_text(encoding="utf-8") == before
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0].count(H_PN) == 1
    assert by_name(rows[0], rows[1])[H_PN] == PROSE   # pipes/slashes preserved verbatim


def test_comp_fit_rederivation_still_wins_over_anything_supplied_in_that_column(tmp_path):
    csv_path = tmp_path / "b-rankings.csv"
    row = make_row(company="Notesco", comp="150-170", comp_fit=PROSE)  # prose smuggled into Comp Fit
    row[HEADERS.index(H_PN)] = PROSE
    write_csv(csv_path, [row])
    norm_contracts.normalize_rankings_csv(str(csv_path), CFG, out=lambda _m: None)
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    got = by_name(rows[0], rows[1])
    assert got["Comp Fit"] == norm_contracts.comp_fit_label("150-170", CFG) == "Below floor"
    assert got[H_PN] == PROSE   # ...and the real notes column is untouched by that re-derivation


def test_notes_column_reaches_the_spreadsheet_wide_wrapped_and_left_aligned(tmp_path):
    cfg_path = tmp_path / "jail.config.json"
    cfg_path.write_text(json.dumps(CFG), encoding="utf-8")
    csv_path = tmp_path / "batch-rankings.csv"
    xlsx_path = tmp_path / "batch-rankings.xlsx"
    row = make_row(company="Notesco")
    row[HEADERS.index(H_PN)] = PROSE
    write_csv(csv_path, [row])
    make_rankings_xlsx.build(str(csv_path), str(xlsx_path), config_path=str(cfg_path))
    ws = load_workbook(str(xlsx_path))["Job Rankings"]
    headers = [c.value for c in ws[1]]
    assert headers[headers.index("Comp + Lifestyle Fit") + 1] == H_PN
    col = headers.index(H_PN) + 1
    assert ws.cell(2, col).value == PROSE
    assert ws.cell(2, col).alignment.horizontal == "left"
    assert ws.cell(2, col).alignment.wrap_text is True
    assert ws.column_dimensions[ws.cell(1, col).column_letter].width == 46


def test_a_legacy_csv_regenerates_to_xlsx_with_the_column_inserted_not_shifted(tmp_path):
    cfg_path = tmp_path / "jail.config.json"
    cfg_path.write_text(json.dumps(CFG), encoding="utf-8")
    csv_path = tmp_path / "batch-rankings.csv"
    xlsx_path = tmp_path / "batch-rankings.xlsx"
    write_no_pn_csv(csv_path, [no_pn_row(company="Notesco")])
    make_rankings_xlsx.build(str(csv_path), str(xlsx_path), config_path=str(cfg_path))
    ws = load_workbook(str(xlsx_path))["Job Rankings"]
    headers = [c.value for c in ws[1]]
    assert headers[headers.index("Comp + Lifestyle Fit") + 1] == H_PN
    got = by_name(headers, [c.value for c in ws[2]])
    assert (got[H_PN] or "") == ""
    assert got["Mission Fit Notes"] == "m"
    assert got["Top Concerns"] == "c"
    assert got["Job File"] == "notesco.txt"
    assert got["Data Completeness"] == "✓ complete"
