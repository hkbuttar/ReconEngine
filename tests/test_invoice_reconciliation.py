"""Tests for invoice reconciliation's combined absolute+relative
materiality rule -- specifically re-testing the bug found and fixed during
this project (invoice_recon/README.md): an absolute-only threshold let
large relative errors (a doubled fee) through unflagged on tiny-notional
trades. These tests pin that fix down so it can't silently regress.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "invoice_recon"))
from generate_invoice import (  # noqa: E402
    MATERIALITY_THRESHOLD_PCT,
    MATERIALITY_THRESHOLD_USD,
    reconcile_invoice,
)


def _expected(ref="binance:1", venue="binance", expected_fee="1.00000000"):
    return {"trade_id_ref": ref, "venue": venue, "notional": "10000.00000000",
            "taker_fee_bps_applied": 10.0, "expected_fee_usd": expected_fee}


class TestCombinedMaterialityRule:
    def test_tiny_absolute_and_tiny_relative_diff_is_matched(self):
        expected = _expected(expected_fee="1.00000000")
        actual_by_ref = {"binance:1": {"actual_fee_usd": "1.00500000", "injected_discrepancy_type": "rounding_error"}}
        result = reconcile_invoice([expected], actual_by_ref)[0]
        assert result["match_status"] == "matched"

    def test_doubled_fee_on_a_tiny_trade_is_still_flagged(self):
        # The exact bug this project found: a doubled ($0.0001 -> $0.0002)
        # fee is only $0.0001 in absolute terms -- well under the $0.01
        # absolute bar -- but 100% relative, which must still be caught.
        expected = _expected(expected_fee="0.00010000")
        actual_by_ref = {"binance:1": {"actual_fee_usd": "0.00020000", "injected_discrepancy_type": "double_billed"}}
        result = reconcile_invoice([expected], actual_by_ref)[0]
        assert result["match_status"] == "discrepant"

    def test_large_absolute_diff_is_flagged_even_if_relatively_small(self):
        expected = _expected(expected_fee="1000.00000000")
        actual_by_ref = {"binance:1": {"actual_fee_usd": "1015.00000000", "injected_discrepancy_type": "rate_misapplied"}}
        result = reconcile_invoice([expected], actual_by_ref)[0]
        assert result["match_status"] == "discrepant"

    def test_missing_actual_line_is_missing_not_discrepant(self):
        expected = _expected()
        result = reconcile_invoice([expected], actual_by_ref={})[0]
        assert result["match_status"] == "missing"
        assert result["actual_fee_usd"] is None

    def test_exact_match_is_matched(self):
        expected = _expected(expected_fee="5.00000000")
        actual_by_ref = {"binance:1": {"actual_fee_usd": "5.00000000", "injected_discrepancy_type": "none"}}
        result = reconcile_invoice([expected], actual_by_ref)[0]
        assert result["match_status"] == "matched"
        assert float(result["delta_usd"]) == 0.0

    def test_thresholds_are_the_disclosed_documented_values(self):
        # Guards against a silent threshold change slipping past review --
        # invoice_recon/README.md documents these exact numbers.
        assert MATERIALITY_THRESHOLD_USD == 0.01
        assert MATERIALITY_THRESHOLD_PCT == 0.10
