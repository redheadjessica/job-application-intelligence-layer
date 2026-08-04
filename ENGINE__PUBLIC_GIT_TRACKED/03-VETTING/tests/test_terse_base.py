"""Unit tests for update_rankings_row.terse_base — the base-resume name normalizer.

The "Tailored? (Base Resume)" column must read identically for the same base no matter how the
tailoring agent phrased it, and must match the resume FILES/FOLDERS on disk, which use a spaced
HYPHEN separator (e.g. "Acme - Senior PM, Growth"), not an em/en-dash. All company/role names
below are synthetic — the normalizer is generic and carries no candidate's real base list.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import update_rankings_row as U


def test_emdash_separator_becomes_hyphen():
    assert U.terse_base("Acme — Lead PM (6/17/26)") == "Acme - Lead PM (6/17/26)"
    assert U.terse_base("Globex — Sr. PM, Consumer (7/17/26)") == "Globex - Sr. PM, Consumer (7/17/26)"


def test_endash_separator_becomes_hyphen():
    assert U.terse_base("Initech (East) – Lead PM (6/17/26)") == "Initech (East) - Lead PM (6/17/26)"


def test_hyphen_separator_is_left_alone():
    assert U.terse_base("Umbra - Staff PM (7/8/26)") == "Umbra - Staff PM (7/8/26)"


def test_product_manager_is_abbreviated_to_pm():
    assert U.terse_base("Hooli — Product Manager, Consumer (6/25/26)") == "Hooli - PM, Consumer (6/25/26)"
    # matches the "PM" variant another agent wrote for the same base
    assert U.terse_base("Hooli - PM, Consumer (6/25/26)") == "Hooli - PM, Consumer (6/25/26)"


def test_hyphen_form_date_is_not_truncated_at_abbreviation():
    # "(07-17-26)" is not a slash date, so without normalization the name was truncated at "Sr."
    assert U.terse_base("Globex - Sr. PM, Consumer (07-17-26)") == "Globex - Sr. PM, Consumer (7/17/26)"


def test_professional_services_abbreviated():
    assert U.terse_base("Vandelay (West) — Lead PM, Professional Services (6/17/26)") \
        == "Vandelay (West) - Lead PM, Prof. Services (6/17/26)"


def test_trailing_prose_after_date_is_dropped():
    assert U.terse_base("Stark — Staff PM (6/9/26), merged with the Hooli module") \
        == "Stark - Staff PM (6/9/26)"


def test_date_paren_extra_words_collapsed():
    assert U.terse_base("Wayne Labs — Senior PM, Delivery (7/31/26 finalized submission)") \
        == "Wayne Labs - Senior PM, Delivery (7/31/26)"


def test_first_date_wins_when_a_second_base_is_mentioned():
    assert U.terse_base("Initech - Principal PM (7/2/26), built on Hooli - PM, Consumer (6/25/26)") \
        == "Initech - Principal PM (7/2/26)"
