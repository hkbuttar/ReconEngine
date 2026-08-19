# ingestion/ — Multi-Source Ingestion / ETL (Step 4)

## Files

- `acquire_real_trades.py` (Step 1) — pulls real trade data live from
  Binance/Coinbase/Kraken's public APIs into `data/real/`.
- `run_pipeline.py` (Step 4) — validates and loads each source into SQL
  Server, with a full audit trail. **This is the file this step is
  about** — the other two are earlier steps' acquisition scripts.

## What `run_pipeline.py` does

Three sources, each validated then loaded independently, in dependency
order (`clearing_statements`/`exchange_confirms` reference `trades`):

| source | file | represents |
|---|---|---|
| `trades` | `data/real/trades_real.csv` | front-office/exchange execution feed |
| `clearing_statements` | `data/synthetic/clearing_statements.csv` | clearing firm's statement feed |
| `exchange_confirms` | `data/synthetic/exchange_confirms.csv` | exchange's confirmation feed |

**Validation (pre-load, Python-side)**, per source:
- schema check — required columns present
- type checks — price/quantity parse as positive numbers, side is
  `buy`/`sell`, timestamps parse
- duplicate-key detection — no repeated natural key *within the source
  file itself* (`(venue, native_trade_id)` for trades,
  `clearing_ref`/`confirm_ref` for the synthetic sources)
- referential integrity — a non-empty `trade_id_ref` on a synthetic
  record must resolve to a real trade. An **empty** ref is the disclosed,
  expected `orphan` break (`data/synthetic/README.md`) and is valid; a
  **non-empty but unresolvable** ref is a genuine data-quality failure

Rows that fail any check are excluded from the load (not just logged) —
`BULK INSERT` only ever sees the validated subset, written to a filtered
copy of the CSV. A dirty row never reaches the database, and the run
still proceeds with whatever's left rather than failing the whole batch.

**Load**: each source's SQL lives in its own `sql/ingest_*.sql`, using a
session-scoped temp table (`#stg_...`) rather than the permanent staging
tables from Steps 2-3's manual loads — a failed run can no longer leave a
dangling table behind (that happened twice during Step 2/3 debugging).
Loads are **idempotent**: each `INSERT` anti-joins against what's already
in the target table on its natural key, so rerunning against
already-ingested data loads zero new rows instead of erroring on the
unique constraint or duplicating data. Verified by running the pipeline
twice in a row — see `README.md`'s Step 4 status line for the counts.

**Audit**: every run writes a row to `ingestion_audit`
(`sql/schema.sql`) — `started_at`/`completed_at`, `status`
(`running`→`succeeded`/`failed`), `rows_read`/`rows_valid`/`rows_rejected`/`rows_loaded`,
and a JSON `quality_check_summary`. This is what Step 14 (monitoring)
computes ingestion success/failure rate from, and what Step 12 (lineage)
anchors to for "which run produced this row."

## Environment constraint (disclosed)

No local ODBC driver / `pyodbc` is set up in this environment (see
`sql/README.md`) — `run_pipeline.py` shells out to
`docker exec reconengine-sql sqlcmd` rather than connecting directly.
This is a dev-environment workaround, not a design choice; swapping in a
direct `pyodbc` connection would be a small, isolated change (the
validation logic doesn't touch the DB at all).

## Run it

```bash
python3 ingestion/run_pipeline.py
```

Requires the `reconengine-sql` container running with the schema already
loaded (`sql/README.md`).
