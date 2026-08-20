"""Sanity checks for the root-cause taxonomy crosswalk (root_cause/taxonomy.py):
the priority rule (MISSING_RECORD > REFERENCE_DATA > QUANTITY > PRICING >
TIMING > CLEAN), and that every real taxonomy entry has a non-empty
citation, catching an accidentally-blanked source string before it ships.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "root_cause"))
from taxonomy import TAXONOMY, crosswalk  # noqa: E402


class TestCrosswalkPriority:
    def test_missing_status_wins_over_everything(self):
        category, _ = crosswalk("missing", "price_mismatch", "breached")
        assert category == "MISSING_RECORD"

    def test_side_mismatch_wins_over_quantity_and_price(self):
        category, _ = crosswalk("broken", "side_mismatch", "on_time")
        assert category == "REFERENCE_DATA"

    def test_quantity_wins_over_price_and_timing(self):
        category, _ = crosswalk("broken", "quantity_mismatch", "late")
        assert category == "QUANTITY"

    def test_price_wins_over_timing(self):
        category, _ = crosswalk("broken", "price_mismatch", "breached")
        assert category == "PRICING"

    def test_timing_breach_label_maps_to_timing_even_if_matched(self):
        category, _ = crosswalk("matched", "timing_breach", "on_time")
        assert category == "TIMING"

    def test_late_lifecycle_status_alone_maps_to_timing(self):
        category, _ = crosswalk("matched", "none", "late")
        assert category == "TIMING"

    def test_clean_when_nothing_is_wrong(self):
        category, _ = crosswalk("matched", "none", "on_time")
        assert category == "CLEAN"


class TestHasTimingIssueFlag:
    def test_flag_true_on_late_regardless_of_category(self):
        _, has_timing_issue = crosswalk("broken", "quantity_mismatch", "late")
        assert has_timing_issue is True

    def test_flag_false_when_on_time(self):
        _, has_timing_issue = crosswalk("broken", "quantity_mismatch", "on_time")
        assert has_timing_issue is False

    def test_flag_false_when_lifecycle_status_unknown(self):
        _, has_timing_issue = crosswalk("missing", "none", None)
        assert has_timing_issue is False


class TestTaxonomyIntegrity:
    def test_every_category_has_a_nonempty_citation(self):
        for code, entry in TAXONOMY.items():
            assert entry.real_citation.strip() != "", f"{code} has an empty citation"

    def test_every_category_has_a_nonempty_description(self):
        for code, entry in TAXONOMY.items():
            assert entry.description.strip() != "", f"{code} has an empty description"

    def test_crosswalk_can_only_return_categories_defined_in_taxonomy(self):
        combos = [
            ("missing", "none", None), ("broken", "side_mismatch", None),
            ("broken", "quantity_mismatch", None), ("broken", "price_mismatch", None),
            ("matched", "timing_breach", None), ("matched", "none", "late"),
            ("matched", "none", "on_time"),
        ]
        for match_status, break_type, lifecycle_status in combos:
            category, _ = crosswalk(match_status, break_type, lifecycle_status)
            assert category in TAXONOMY, f"crosswalk returned undefined category {category}"
