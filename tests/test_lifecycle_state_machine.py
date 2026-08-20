"""Unit tests for the lifecycle state machine's transition logic: the
gating rule (missing confirm/clearing blocks downstream stages), the
monotonicity guard (settled can't precede confirmed), business-day math
for the T+1 target, and the on_time/late/breached status boundary.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "lifecycle"))
from state_machine import (  # noqa: E402
    BREACH_THRESHOLD,
    _add_business_days,
    _status,
    build_lifecycle,
)


def _trade(venue="binance", native_id="1", traded_at="2026-08-19T12:00:00+00:00", price="68000", quantity="0.01", side="buy", symbol="BTCUSDT"):
    return {"venue": venue, "native_trade_id": native_id, "traded_at": traded_at, "price": price, "quantity": quantity, "side": side, "symbol": symbol}


def _confirm(ref, received_at="2026-08-19T12:05:00+00:00"):
    return {"trade_id_ref": ref, "received_at": received_at}


def _clearing(ref, received_at="2026-08-19T13:00:00+00:00"):
    return {"trade_id_ref": ref, "received_at": received_at}


class TestStatus:
    def test_before_deadline_is_on_time(self):
        entered = dt.datetime(2026, 8, 19, tzinfo=dt.timezone.utc)
        expected = dt.datetime(2026, 8, 20, tzinfo=dt.timezone.utc)
        assert _status(entered, expected) == "on_time"

    def test_exactly_at_deadline_is_on_time(self):
        t = dt.datetime(2026, 8, 19, tzinfo=dt.timezone.utc)
        assert _status(t, t) == "on_time"

    def test_slightly_late_is_late_not_breached(self):
        expected = dt.datetime(2026, 8, 19, tzinfo=dt.timezone.utc)
        entered = expected + dt.timedelta(hours=1)
        assert _status(entered, expected) == "late"

    def test_beyond_breach_threshold_is_breached(self):
        expected = dt.datetime(2026, 8, 19, tzinfo=dt.timezone.utc)
        entered = expected + BREACH_THRESHOLD + dt.timedelta(seconds=1)
        assert _status(entered, expected) == "breached"

    def test_right_at_breach_threshold_is_still_late(self):
        expected = dt.datetime(2026, 8, 19, tzinfo=dt.timezone.utc)
        entered = expected + BREACH_THRESHOLD
        assert _status(entered, expected) == "late"


class TestBusinessDays:
    def test_monday_plus_one_business_day_is_tuesday(self):
        monday = dt.datetime(2026, 8, 17, tzinfo=dt.timezone.utc)  # a real Monday
        assert _add_business_days(monday, 1).weekday() == 1  # Tuesday

    def test_friday_plus_one_business_day_skips_weekend_to_monday(self):
        friday = dt.datetime(2026, 8, 21, tzinfo=dt.timezone.utc)  # a real Friday
        result = _add_business_days(friday, 1)
        assert result.weekday() == 0  # Monday
        assert (result.date() - friday.date()).days == 3

    def test_zero_business_days_returns_same_day_unchanged_in_weekday(self):
        wednesday = dt.datetime(2026, 8, 19, tzinfo=dt.timezone.utc)
        assert _add_business_days(wednesday, 0) == wednesday


class TestGating:
    def test_trade_with_no_confirm_never_reaches_confirmed_or_beyond(self):
        trades = [_trade()]
        lifecycle_rows, settlement_rows, accounting_rows = build_lifecycle(trades, clearing_by_ref={}, confirm_by_ref={})
        stages_reached = {r["stage_code"] for r in lifecycle_rows}
        assert stages_reached == {"captured", "sent_to_clearing"}
        assert settlement_rows == []
        assert accounting_rows == []

    def test_trade_with_confirm_but_no_clearing_stalls_before_settled(self):
        ref = "binance:1"
        trades = [_trade()]
        lifecycle_rows, settlement_rows, accounting_rows = build_lifecycle(
            trades, clearing_by_ref={}, confirm_by_ref={ref: _confirm(ref)}
        )
        stages_reached = {r["stage_code"] for r in lifecycle_rows}
        assert stages_reached == {"captured", "sent_to_clearing", "confirmed"}
        assert settlement_rows == []

    def test_trade_with_both_records_reaches_all_five_stages(self):
        ref = "binance:1"
        trades = [_trade()]
        lifecycle_rows, settlement_rows, accounting_rows = build_lifecycle(
            trades, clearing_by_ref={ref: _clearing(ref)}, confirm_by_ref={ref: _confirm(ref)}
        )
        stages_reached = {r["stage_code"] for r in lifecycle_rows}
        assert stages_reached == {"captured", "sent_to_clearing", "confirmed", "settled", "posted_to_accounting"}
        assert len(settlement_rows) == 1
        assert len(accounting_rows) == 1


class TestMonotonicityGuard:
    def test_settled_is_never_before_confirmed_even_if_clearing_timestamp_predates_it(self):
        ref = "binance:1"
        trades = [_trade(traded_at="2026-08-19T12:00:00+00:00")]
        # confirm arrives late (a simulated timing_breach); clearing's raw
        # timestamp is earlier than that late confirm.
        confirm_by_ref = {ref: _confirm(ref, received_at="2026-08-22T00:00:00+00:00")}
        clearing_by_ref = {ref: _clearing(ref, received_at="2026-08-19T13:00:00+00:00")}
        lifecycle_rows, _, _ = build_lifecycle(trades, clearing_by_ref, confirm_by_ref)

        by_stage = {r["stage_code"]: r for r in lifecycle_rows}
        confirmed_at = dt.datetime.fromisoformat(by_stage["confirmed"]["entered_at"])
        settled_at = dt.datetime.fromisoformat(by_stage["settled"]["entered_at"])
        assert settled_at >= confirmed_at
