# backend/ — FastAPI

Programmatic access to everything the Qlik dashboard shows, for a caller
that isn't Qlik: natural-language query, monitoring/observability
metrics, and lineage lookups, plus general read access to trades and
breaks.

## Endpoints (all live-tested against the real DB)

| endpoint | what it does |
|---|---|
| `GET /health` | basic health check |
| `GET /monitoring/ingestion-health` | `vw_IngestionHealth` |
| `GET /monitoring/match-rate` | `vw_MatchRateByStage` |
| `GET /monitoring/break-aging` | `vw_BreakAgingDistribution` |
| `GET /monitoring/invoice-discrepancy` | `vw_InvoiceDiscrepancyRate` |
| `GET /monitoring/alerts?acknowledged=false` | current alerts |
| `GET /lineage/graph` | the full asset-level lineage graph |
| `GET /lineage/trace/{venue}/{native_trade_id}` | one trade's real row data across every table (`lineage/trace.py`, wrapped) |
| `GET /query?question=...` | natural-language → SQL → results (`llm_assist/nl_query.py`, wrapped) |
| `GET /trades/{venue}/{native_trade_id}` | single trade lookup |
| `GET /breaks?category=...&stage=...` | filtered break listing |

Interactive docs at `/docs` (FastAPI's auto-generated OpenAPI UI) once
running.

## A real bug found and fixed during live testing

`run_query_json()` originally used `|` as the delimiter for parsing
`sqlcmd`'s output into JSON. **All 254 `CRITICAL_AGED_BREAK` alerts
silently vanished** from `/monitoring/alerts` — not an error, just gone,
which is worse. Root cause: `monitoring/alert_rules.py` builds that
alert's `entity_ref` as `"{trade_id}|{stage}"` — a literal `|` inside the
data itself, colliding with `|` as the output delimiter and breaking the
column count for every row that contained it, so they were silently
dropped by the (deliberately strict) `len(values) != len(header)` check
rather than corrupting the response.

Fixed by switching the delimiter to `\x1f` (ASCII unit separator) — a
character no real field in this schema legitimately contains, rather
than assuming a printable character like `|` is safe. Verified live:
alert count went from 438 (silently wrong) to 692 (correct, matching
`254 + 438` exactly).

## Dual-mode DB access

`backend/db_client.py`: a real `pyodbc` connection when
`RECONENGINE_ODBC_CONNECTION_STRING` is set (production), the local
`docker exec reconengine-sql sqlcmd` mechanism otherwise (dev). Both
modes are actually verified, not just one — see `DEPLOYMENT.md` for how
the `pyodbc` path was built and run end to end despite this machine's own
macOS ODBC-driver install blocker, plus two more real bugs found and
fixed while doing it.

## Run it (local dev)

```bash
python3 -m uvicorn backend.main:app --port 8000
```

Requires `reconengine-sql` running (`sql/README.md`) for every endpoint
except `/health`, and `ANTHROPIC_API_KEY` in `.env` for `/query`. For a
real deployment (Docker image, Render, production DB connection), see
`DEPLOYMENT.md`.
