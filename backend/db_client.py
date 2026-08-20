"""Dual-mode database access: a real pyodbc connection when
RECONENGINE_ODBC_CONNECTION_STRING is set (the deployed/production path),
falling back to the `docker exec reconengine-sql sqlcmd` mechanism used
everywhere else in this project's local dev environment (sql/README.md's
disclosed no-local-ODBC-driver constraint) when it isn't.

Both paths expose the same run_query_json(sql) -> list[dict] interface,
so backend/main.py's route handlers never need to know which one is
active.

Both paths are verified live, not just written to spec. Installing the
Microsoft ODBC driver directly on the host (macOS) requires updating
Xcode Command Line Tools -- a system-level change needing sudo and a
large download, hit right after this project's own disk-space incident
(README.md's Results section) and not worth pushing through for a local
dev convenience. But the pyodbc path this module actually runs in
production is the one inside the Linux deploy container (`Dockerfile`),
where installing the driver is a plain `apt-get` with no such blocker --
that image was built and run locally, pointed at the real
`reconengine-sql` container over Docker's bridge network, and every
DB-backed endpoint verified to return the same real numbers as the
sqlcmd path (`DEPLOYMENT.md`).
"""

from __future__ import annotations

import os
import subprocess

_DELIM = "\x1f"  # see backend/README.md's "bug found and fixed" section --
# a real "|" delimiter collision with alert data ("trade_id|stage") that
# silently dropped rows is why this isn't a plain "|".

CONTAINER = "reconengine-sql"
SA_PASSWORD = "ReconEngine!2026"
SQLCMD = ["docker", "exec", CONTAINER, "/opt/mssql-tools18/bin/sqlcmd",
          "-S", "localhost", "-U", "sa", "-P", SA_PASSWORD, "-C", "-d", "reconengine"]


class QueryError(RuntimeError):
    pass


def _run_via_sqlcmd(query: str) -> list[dict]:
    try:
        result = subprocess.run(
            SQLCMD + ["-s", _DELIM, "-W", "-Q", f"SET NOCOUNT ON; {query}"],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError as exc:
        # No `docker` in this environment (e.g. inside the deploy
        # container, which has neither `docker` nor a socket) and no
        # RECONENGINE_ODBC_CONNECTION_STRING set either -- found live
        # while verifying the deploy image's failure mode (DEPLOYMENT.md):
        # without this, the caller only ever saw an opaque generic 500.
        raise QueryError(
            "no database connection available: RECONENGINE_ODBC_CONNECTION_STRING is not set, "
            "and the local docker-exec fallback requires `docker` on PATH (dev-only, not for deployed environments)"
        ) from exc
    if result.returncode != 0:
        raise QueryError(result.stdout or result.stderr)

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    header = [h.strip() for h in lines[0].split(_DELIM)]
    rows = []
    for line in lines[1:]:
        if set(line.strip()) <= {"-", _DELIM}:
            continue
        values = [v.strip() for v in line.split(_DELIM)]
        if len(values) != len(header):
            continue
        rows.append(dict(zip(header, values)))
    return rows


def _run_via_pyodbc(query: str) -> list[dict]:
    import pyodbc  # imported lazily -- only required when this path is actually used

    conn_str = os.environ["RECONENGINE_ODBC_CONNECTION_STRING"]
    with pyodbc.connect(conn_str, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def run_query_json(query: str) -> list[dict]:
    if os.environ.get("RECONENGINE_ODBC_CONNECTION_STRING"):
        return _run_via_pyodbc(query)
    return _run_via_sqlcmd(query)
