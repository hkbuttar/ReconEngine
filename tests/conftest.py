"""Shared helpers for the DB-dependent test modules. These tests need the
live reconengine-sql container (sql/README.md) -- each DB test module
checks DB_AVAILABLE and applies pytest.mark.skipif itself, so the
pure-unit test modules (test_matching_engine.py, test_lifecycle_state_machine.py,
test_taxonomy.py, test_invoice_reconciliation.py) stay runnable anywhere
without Docker, and DB tests are skipped (not failed) when it isn't reachable.
"""

from __future__ import annotations

import subprocess

CONTAINER = "reconengine-sql"
SA_PASSWORD = "ReconEngine!2026"
SQLCMD = ["docker", "exec", CONTAINER, "/opt/mssql-tools18/bin/sqlcmd",
          "-S", "localhost", "-U", "sa", "-P", SA_PASSWORD, "-C", "-d", "reconengine"]


def db_available() -> bool:
    try:
        result = subprocess.run(SQLCMD + ["-Q", "SELECT 1"], capture_output=True, text=True, timeout=15)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def run_query(query: str) -> subprocess.CompletedProcess:
    return subprocess.run(SQLCMD + ["-Q", query], capture_output=True, text=True, timeout=30)


def scalar(query: str) -> str:
    result = subprocess.run(SQLCMD + ["-h", "-1", "-W", "-Q", f"SET NOCOUNT ON; {query}"],
                             capture_output=True, text=True, timeout=30)
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[0] if lines else ""


DB_AVAILABLE = db_available()
