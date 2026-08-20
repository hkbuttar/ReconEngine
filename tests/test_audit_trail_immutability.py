"""Verifies audit_log's immutability is enforced by the database engine
itself, not by convention -- the load-bearing claim of Step 11 (see
audit_trail/README.md). Re-proves what was found live during that build:
UPDATE and DELETE both fail with SQL Server error 37359 against an
append-only LEDGER table.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from conftest import DB_AVAILABLE, run_query, scalar  # noqa: E402

pytestmark = pytest.mark.skipif(not DB_AVAILABLE, reason="reconengine-sql container not reachable")


class TestAuditLogImmutability:
    def test_audit_log_is_populated(self):
        count = int(scalar("SELECT COUNT(*) FROM audit_log;"))
        assert count > 0

    def test_update_against_audit_log_is_rejected(self):
        result = run_query("UPDATE audit_log SET details = 'tampered' WHERE audit_log_id = 1;")
        assert "37359" in result.stdout
        assert "not allowed" in result.stdout.lower()

    def test_delete_against_audit_log_is_rejected(self):
        result = run_query("DELETE FROM audit_log WHERE audit_log_id = 1;")
        assert "37359" in result.stdout
        assert "not allowed" in result.stdout.lower()

    def test_tampering_attempts_did_not_actually_change_the_row(self):
        # Belt-and-suspenders: confirm the rejected UPDATE/DELETE above
        # really left row 1 untouched, not just that SQL Server complained.
        details = scalar("SELECT details FROM audit_log WHERE audit_log_id = 1;")
        assert details != "tampered"
        exists = scalar("SELECT COUNT(*) FROM audit_log WHERE audit_log_id = 1;")
        assert exists == "1"

    def test_table_is_actually_ledger_enabled(self):
        # Confirms this is real engine-level ledger enforcement, not a
        # trigger or app-level convention that happens to also reject
        # writes -- queries SQL Server 2022's own ledger_type catalog
        # column directly -- verified live (not assumed from memory)
        # against sys.tables.ledger_type_desc: 3 = APPEND_ONLY_LEDGER_TABLE,
        # 0 = NON_LEDGER_TABLE for an ordinary table like `trades`.
        ledger_type = scalar("SELECT ledger_type FROM sys.tables WHERE name = 'audit_log';")
        assert ledger_type == "3"
        ledger_type_desc = scalar("SELECT ledger_type_desc FROM sys.tables WHERE name = 'audit_log';")
        assert ledger_type_desc == "APPEND_ONLY_LEDGER_TABLE"

    def test_a_normal_non_ledger_table_does_not_share_this_restriction(self):
        # Contrast check: trades is a normal table, so UPDATE must succeed
        # there -- confirms the rejection above is specific to audit_log's
        # ledger property, not some global read-only mode on the DB.
        trade_id = scalar("SELECT TOP 1 trade_id FROM trades;")
        original_symbol = scalar(f"SELECT symbol FROM trades WHERE trade_id = {trade_id};")
        try:
            result = run_query(f"UPDATE trades SET symbol = symbol WHERE trade_id = {trade_id};")
            assert "Msg " not in result.stdout
        finally:
            run_query(f"UPDATE trades SET symbol = '{original_symbol}' WHERE trade_id = {trade_id};")
