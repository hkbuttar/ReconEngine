"""Unit tests for the matching engine's classify_stage() -- the plan's
explicitly highest-priority test target, since every downstream table
(root_cause_labels, break_aging, exception reports) depends on it being
right. Exercises the real function with controlled inputs, not the full
pipeline against live data -- that's covered separately by the
self-validation the module already runs against ground truth
(reconciliation/README.md).
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "reconciliation"))
from matching_engine import (  # noqa: E402
    PRICE_TOLERANCE_PCT,
    QUANTITY_TOLERANCE_PCT,
    _rel_diff,
    classify_stage,
    fuzzy_match_orphans,
)


def _trade(price="68000.00000000", quantity="0.01000000", side="buy"):
    return {"venue": "binance", "native_trade_id": "1", "price": price, "quantity": quantity, "side": side}


def _synthetic(price="68000.00000000", quantity="0.01000000", side="buy", break_type="none"):
    return {"reported_price": price, "reported_quantity": quantity, "reported_side": side, "injected_break_type": break_type}


class TestMissingClassification:
    def test_no_synthetic_record_is_missing(self):
        result = classify_stage(_trade(), None)
        assert result["match_status"] == "missing"
        assert result["price_diff_pct"] == ""
        assert result["side_match"] == ""


class TestCleanMatch:
    def test_identical_values_match(self):
        result = classify_stage(_trade(), _synthetic())
        assert result["match_status"] == "matched"
        assert float(result["price_diff_pct"]) == 0.0
        assert float(result["quantity_diff_pct"]) == 0.0
        assert result["side_match"] is True


class TestPriceBreaks:
    def test_price_beyond_tolerance_is_broken(self):
        # 1% off -- well beyond the 0.01% tolerance
        result = classify_stage(_trade(price="68000"), _synthetic(price="68680", break_type="price_mismatch"))
        assert result["match_status"] == "broken"

    def test_price_within_tolerance_still_matches(self):
        # 0.005% off -- half the tolerance, should NOT be flagged
        result = classify_stage(_trade(price="68000"), _synthetic(price="68003.4"))
        assert result["match_status"] == "matched"

    def test_just_inside_tolerance_matches(self):
        # 90% of the tolerance -- comfortably inside, avoids asserting
        # float equality at the exact boundary (fragile: string formatting
        # and re-parsing the boundary value can round either side of it).
        price = 68000 * (1 + PRICE_TOLERANCE_PCT * 0.9)
        result = classify_stage(_trade(price="68000"), _synthetic(price=f"{price:.8f}"))
        assert result["match_status"] == "matched"

    def test_just_outside_tolerance_is_broken(self):
        price = 68000 * (1 + PRICE_TOLERANCE_PCT * 1.5)
        result = classify_stage(_trade(price="68000"), _synthetic(price=f"{price:.8f}"))
        assert result["match_status"] == "broken"


class TestQuantityBreaks:
    def test_quantity_beyond_tolerance_is_broken(self):
        result = classify_stage(_trade(quantity="0.01"), _synthetic(quantity="0.0102", break_type="quantity_mismatch"))
        assert result["match_status"] == "broken"

    def test_quantity_within_tolerance_matches(self):
        boundary_qty = 0.01 * (1 + QUANTITY_TOLERANCE_PCT / 2)
        result = classify_stage(_trade(quantity="0.01"), _synthetic(quantity=f"{boundary_qty:.8f}"))
        assert result["match_status"] == "matched"


class TestSideBreaks:
    def test_side_mismatch_is_broken_even_with_identical_price_qty(self):
        result = classify_stage(_trade(side="buy"), _synthetic(side="sell", break_type="side_mismatch"))
        assert result["match_status"] == "broken"
        assert result["side_match"] is False

    def test_timing_breach_does_not_affect_field_match(self):
        # timing_breach perturbs only the timestamp, never price/qty/side --
        # classify_stage has no timestamp input at all, so it must report
        # matched regardless of the (irrelevant here) break label.
        result = classify_stage(_trade(), _synthetic(break_type="timing_breach"))
        assert result["match_status"] == "matched"


class TestRelDiff:
    def test_zero_expected_zero_actual_is_zero_diff(self):
        assert _rel_diff(0.0, 0.0) == 0.0

    def test_zero_expected_nonzero_actual_is_infinite(self):
        assert _rel_diff(0.0, 1.0) == float("inf")

    def test_symmetric_around_expected(self):
        assert abs(_rel_diff(100.0, 110.0) - 0.10) < 1e-9


class TestFuzzyMatchOrphans:
    def test_candidate_within_tolerance_is_found(self):
        missing_trades = [
            {"venue": "binance", "symbol": "BTCUSDT", "traded_at": "2026-08-19T12:00:00+00:00",
             "price": "68000", "quantity": "0.01", "native_trade_id": "1"}
        ]
        orphans = [{"clearing_ref": "ORPHAN-1", "reported_venue": "binance", "reported_symbol": "BTCUSDT",
                    "received_at": "2026-08-19T12:10:00+00:00", "reported_price": "68100", "reported_quantity": "0.0101"}]
        results = fuzzy_match_orphans(missing_trades, orphans, "clearing_ref")
        assert results[0]["candidate_count"] == 1

    def test_candidate_outside_time_window_is_excluded(self):
        missing_trades = [
            {"venue": "binance", "symbol": "BTCUSDT", "traded_at": "2026-08-19T12:00:00+00:00",
             "price": "68000", "quantity": "0.01", "native_trade_id": "1"}
        ]
        orphans = [{"clearing_ref": "ORPHAN-1", "reported_venue": "binance", "reported_symbol": "BTCUSDT",
                    "received_at": "2026-08-19T15:00:00+00:00", "reported_price": "68000", "reported_quantity": "0.01"}]
        results = fuzzy_match_orphans(missing_trades, orphans, "clearing_ref")
        assert results[0]["candidate_count"] == 0

    def test_different_venue_never_matches(self):
        missing_trades = [
            {"venue": "kraken", "symbol": "XBTUSD", "traded_at": "2026-08-19T12:00:00+00:00",
             "price": "68000", "quantity": "0.01"}
        ]
        orphans = [{"clearing_ref": "ORPHAN-1", "reported_venue": "binance", "reported_symbol": "BTCUSDT",
                    "received_at": "2026-08-19T12:00:00+00:00", "reported_price": "68000", "reported_quantity": "0.01"}]
        results = fuzzy_match_orphans(missing_trades, orphans, "clearing_ref")
        assert results[0]["candidate_count"] == 0
