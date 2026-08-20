"""Verifies the live schema's constraints are actually enforced by the
database engine, not just declared in sql/schema.sql -- a CHECK/UNIQUE
constraint that silently isn't applied (wrong syntax, disabled, etc.) is
exactly the kind of thing that only a live test against the real engine
catches, matching this project's practice of verifying against the real
instance rather than trusting the DDL file alone (sql/README.md's own
build history has two examples of DDL that looked right but wasn't).
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from conftest import DB_AVAILABLE, run_query, scalar  # noqa: E402

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="reconengine-sql container not reachable")


class TestUniqueConstraints:
    def test_duplicate_venue_native_trade_id_is_rejected(self):
        # Grab a real (venue, native_trade_id) pair and try to insert a duplicate.
        row = scalar("SELECT TOP 1 CONCAT(venue, '|', native_trade_id) FROM trades;")
        venue, native_id = row.split("|", 1)
        result = run_query(
            f"INSERT INTO trades (venue, native_trade_id, symbol, side, price, quantity, traded_at) "
            f"VALUES ('{venue}', '{native_id}', 'TEST', 'buy', 1, 1, SYSUTCDATETIME());"
        )
        assert "Msg " in result.stdout
        assert "UNIQUE" in result.stdout.upper()


class TestCheckConstraints:
    def test_invalid_side_value_is_rejected(self):
        result = run_query(
            "INSERT INTO trades (venue, native_trade_id, symbol, side, price, quantity, traded_at) "
            "VALUES ('test_venue', 'ck_test_1', 'TEST', 'hold', 1, 1, SYSUTCDATETIME());"
        )
        assert "Msg " in result.stdout
        assert "CHECK" in result.stdout.upper()

    def test_negative_price_is_rejected(self):
        result = run_query(
            "INSERT INTO trades (venue, native_trade_id, symbol, side, price, quantity, traded_at) "
            "VALUES ('test_venue', 'ck_test_2', 'TEST', 'buy', -5, 1, SYSUTCDATETIME());"
        )
        assert "Msg " in result.stdout
        assert "CHECK" in result.stdout.upper()

    def test_invalid_match_status_on_reconciliation_results_is_rejected(self):
        # Every real trade already has both stages populated (see
        # TestExpectedRowCounts below) -- reusing one would trip the
        # UNIQUE constraint instead of isolating the CHECK constraint.
        # Insert a fresh, throwaway trade first so this test hits exactly
        # the constraint it's meant to test.
        run_query(
            "INSERT INTO trades (venue, native_trade_id, symbol, side, price, quantity, traded_at) "
            "VALUES ('test_venue', 'ck_test_3', 'TEST', 'buy', 1, 1, SYSUTCDATETIME());"
        )
        try:
            trade_id = scalar("SELECT trade_id FROM trades WHERE venue = 'test_venue' AND native_trade_id = 'ck_test_3';")
            result = run_query(
                f"INSERT INTO reconciliation_results (trade_id, stage, match_status) "
                f"VALUES ({trade_id}, 'clearing', 'not_a_real_status');"
            )
            assert "Msg " in result.stdout
            assert "CHECK" in result.stdout.upper()
        finally:
            run_query("DELETE FROM trades WHERE venue = 'test_venue' AND native_trade_id = 'ck_test_3';")

    def test_invalid_alert_severity_is_rejected(self):
        result = run_query(
            "INSERT INTO alerts (alert_type, severity, description, threshold_breached) "
            "VALUES ('TEST', 'catastrophic', 'test', 'test');"
        )
        assert "Msg " in result.stdout
        assert "CHECK" in result.stdout.upper()


class TestForeignKeyConstraints:
    def test_reconciliation_result_with_nonexistent_trade_id_is_rejected(self):
        result = run_query(
            "INSERT INTO reconciliation_results (trade_id, stage, match_status) "
            "VALUES (-999999, 'clearing', 'matched');"
        )
        assert "Msg " in result.stdout
        assert "FOREIGN KEY" in result.stdout.upper()


class TestExpectedRowCounts:
    """Not constraint tests, but a cheap sanity check that the core tables
    are actually populated and internally consistent -- catches an empty
    or partially-loaded DB before the constraint tests above would give
    misleading passes (e.g. "no duplicate rejected" because there was
    nothing to duplicate)."""

    def test_trades_table_is_populated(self):
        count = int(scalar("SELECT COUNT(*) FROM trades;"))
        assert count > 0

    def test_reconciliation_results_row_count_is_exactly_twice_trades(self):
        # One row per (trade, stage), 2 stages -- an exact 2x relationship,
        # not just "greater than zero".
        trades = int(scalar("SELECT COUNT(*) FROM trades;"))
        results = int(scalar("SELECT COUNT(*) FROM reconciliation_results;"))
        assert results == trades * 2
