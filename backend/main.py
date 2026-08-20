"""FastAPI backend: natural-language query, monitoring/observability
metrics, and lineage lookups -- programmatic access to everything the
Qlik dashboard shows, for a caller that isn't Qlik.

DB access goes through `backend/db_client.py` -- a real pyodbc connection
in production (when `RECONENGINE_ODBC_CONNECTION_STRING` is set) or the
local `docker exec reconengine-sql sqlcmd` mechanism used everywhere else
in this project's dev environment otherwise (sql/README.md). See that
module's docstring for the disclosed dual-mode design and what's been
verified in each mode.
"""

from __future__ import annotations

import os
import pathlib
import sys

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

load_dotenv()

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lineage"))
sys.path.insert(0, str(REPO_ROOT / "llm_assist"))

sys.path.insert(0, str(REPO_ROOT / "backend"))

from db_client import QueryError, run_query_json as _run_query_json  # noqa: E402
from graph import EDGES, NODES  # noqa: E402
from trace import TABLE_SOURCES, find_rows  # noqa: E402


def _sql_escape(value: str) -> str:
    return value.replace("'", "''")


app = FastAPI(
    title="ReconEngine API",
    description="Programmatic access to reconciliation data: NL query, monitoring metrics, lineage lookups.",
    version="1.0.0",
)


def run_query_json(query: str) -> list[dict]:
    try:
        return _run_query_json(query)
    except QueryError as exc:
        raise HTTPException(status_code=502, detail=f"database query failed: {exc}") from exc


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --- Monitoring / observability (Step 14's views, exposed here) ------------

@app.get("/monitoring/ingestion-health")
def ingestion_health() -> list[dict]:
    return run_query_json("SELECT * FROM vw_IngestionHealth;")


@app.get("/monitoring/match-rate")
def match_rate() -> list[dict]:
    return run_query_json("SELECT * FROM vw_MatchRateByStage;")


@app.get("/monitoring/break-aging")
def break_aging_distribution() -> list[dict]:
    return run_query_json("SELECT * FROM vw_BreakAgingDistribution;")


@app.get("/monitoring/invoice-discrepancy")
def invoice_discrepancy_rate() -> list[dict]:
    return run_query_json("SELECT * FROM vw_InvoiceDiscrepancyRate;")


@app.get("/monitoring/alerts")
def alerts(acknowledged: bool | None = None) -> list[dict]:
    query = "SELECT alert_type, severity, entity_ref, description, triggered_at, acknowledged FROM alerts"
    if acknowledged is not None:
        query += f" WHERE acknowledged = {1 if acknowledged else 0}"
    return run_query_json(query + " ORDER BY triggered_at DESC;")


# --- Lineage -----------------------------------------------------------------

@app.get("/lineage/graph")
def lineage_graph() -> dict:
    return {
        "nodes": [{"table": n.table, "is_synthetic": n.is_synthetic, "description": n.description} for n in NODES.values()],
        "edges": [{"source_table": e.source_table, "target_table": e.target_table, "transform_step": e.transform_step} for e in EDGES],
    }


@app.get("/lineage/trace/{venue}/{native_trade_id}")
def lineage_trace(venue: str, native_trade_id: str) -> dict:
    trade_ref = f"{venue}:{native_trade_id}"
    result = {}
    for table in ["trades_real.csv"] + list(TABLE_SOURCES.keys())[1:]:
        node = NODES.get(table)
        rows = find_rows(table, trade_ref)
        result[table] = {
            "is_synthetic": node.is_synthetic if node else None,
            "rows": rows,
        }
    if not any(v["rows"] for v in result.values()):
        raise HTTPException(status_code=404, detail=f"no data found for trade {trade_ref}")
    return result


# --- Natural-language query (Step 8's nl_query.py, exposed here) -----------

@app.get("/query")
def nl_query(question: str) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured on this server")

    from nl_query import is_safe_select, nl_to_sql

    sql = nl_to_sql(question)
    if sql.startswith("NO_QUERY:"):
        return {"question": question, "sql": None, "error": sql[len("NO_QUERY:"):].strip(), "rows": None}
    if not is_safe_select(sql):
        return {"question": question, "sql": sql, "error": "generated SQL failed the read-only safety check; not executed", "rows": None}

    rows = run_query_json(sql)
    return {"question": question, "sql": sql, "error": None, "rows": rows}


# --- General read access beyond the 3 named capabilities --------------------

@app.get("/trades/{venue}/{native_trade_id}")
def get_trade(venue: str, native_trade_id: str) -> dict:
    rows = run_query_json(
        f"SELECT trade_id, venue, native_trade_id, symbol, side, price, quantity, traded_at "
        f"FROM trades WHERE venue = '{_sql_escape(venue)}' AND native_trade_id = '{_sql_escape(native_trade_id)}';"
    )
    if not rows:
        raise HTTPException(status_code=404, detail="trade not found")
    return rows[0]


@app.get("/breaks")
def list_breaks(category: str | None = None, stage: str | None = None, limit: int = 50) -> list[dict]:
    query = "SELECT trade_id, stage, root_cause_category, has_timing_issue FROM root_cause_labels WHERE root_cause_category <> 'CLEAN'"
    if category:
        query += f" AND root_cause_category = '{_sql_escape(category)}'"
    if stage:
        query += f" AND stage = '{_sql_escape(stage)}'"
    query += " ORDER BY trade_id;"
    rows = run_query_json(query)
    return rows[:limit]
