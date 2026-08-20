# performance/ — Volume & Performance Testing

## Volume-scaling methodology (disclosed)

Real trade data is 11,008 real trades over ~7 minutes — not a
high-volume day. `generate_volume_dataset.py` scales it to 200,000 trades
via **disclosed replication**, not fabrication: each replica copies a
real trade's **price, quantity, and side verbatim** (actual real market
data), gets a synthetic new `native_trade_id` (the real venue never
issued a second id for the same trade — the id is what's synthesized),
and a new `traded_at` redistributed across a simulated 24-hour trading
day. `generate_volume_synthetic.py` then generates matching
clearing/confirm records by **reusing the same `generate()`
function** against the larger input — same disclosed discrepancy rates,
just at volume, not a re-derived methodology. Output: `volume_trades.csv`
(200,000 rows), `volume_clearing_statements.csv` (~198,000 rows) — a
separate dataset, never touching the live schema's real 11,008-trade data.

## Matching engine throughput

`benchmark_matching_engine.py` runs the **actual**
`reconciliation/matching_engine.py.classify_stage()` — not a stand-in —
against the volume dataset:

| | value |
|---|---:|
| CSV load | 0.90s |
| matching (400,000 classifications) | 0.44s |
| throughput | 452,610 trades/sec |

**CSV loading is slower than matching itself** at this volume — the
matching *logic* is not a meaningful bottleneck at any realistic trade
count. A naive extrapolation (452,610/sec × 86,400s) implies ~39 billion
trades/day — reported here only to make the point that it's a
meaningless number, not a real capacity claim: real systems are bounded
by I/O and data movement, not in-memory Python list operations. The SQL
load benchmark below measures the bound that actually matters.

## SQL load throughput — and a real, honest negative result

`sql/perf_load.sql` runs the **actual production load pattern**
(`sql/ingest_trades.sql`/`ingest_clearing.sql`'s `BULK INSERT` +
`CHARINDEX`-based join) against dedicated `perf_trades`/
`perf_clearing_statements` tables, timed server-side
(`SET STATISTICS TIME ON`, not wall-clock — excludes `docker exec`
overhead):

| step | rows | elapsed | CPU |
|---|---:|---:|---:|
| BULK INSERT trades staging | 200,000 | 207ms | 191ms |
| INSERT...SELECT → `perf_trades` | 200,000 | 1,121ms | 978ms |
| BULK INSERT clearing staging | 197,964 | 311ms | 266ms |
| INSERT...SELECT → `perf_clearing_statements` (join) | 197,964 | 1,329ms | 2,503ms |

The join step's CPU time (2,503ms) is **2.5× the plain-insert step's**
(978ms) for a comparable row count — a real, measured cost, not assumed.
Hypothesis: the `CHARINDEX`/`SUBSTRING` string-parsing embedded in the
join predicate is non-sargable, preventing an index seek against
`perf_trades`' `(venue, native_trade_id)` unique index.

**Tested the fix, honestly reported that it didn't work.**
`sql/perf_load_optimized.sql` pre-splits `trade_id_ref` into real
`venue_ref`/`native_id_ref` columns in a single `UPDATE` pass *before*
joining, so the join itself becomes a plain equi-join. Result: **worse**,
not better — 2,079ms total (843ms `UPDATE` + 1,236ms join) vs. 1,329ms
for the original single-step join. The string-parsing cost didn't go
away; it just moved to a separate pass, plus added a full extra table
write.

**Root cause, verified via the actual execution plan** (`SET
SHOWPLAN_TEXT ON`), not guessed at:

```
|--Hash Match(Right Outer Join, HASH:([t].[venue],[t].[native_trade_id])=([Expr1003],[Expr1004]), ...)
     |--Index Scan(OBJECT:(...perf_trades.uq_perf_trades_venue_native...))
          |--Table Scan(OBJECT:(...#stg_check...))
```

SQL Server already uses a **Hash Match join**, not a nested-loop index
seek, for this batch pattern — at 200,000-row scale, the optimizer
builds an in-memory hash table from `perf_trades` (an **Index Scan**,
not a seek) and probes it once per staging row, computing the `CHARINDEX`
expression during the probe either way. The join key's sargability,
which matters for point lookups, is irrelevant here because SQL Server
never intended to seek row-by-row for a batch join this size. The
"obvious" fix targeted the wrong mechanism.

**What this means operationally**: the real per-row `CHARINDEX`/
`SUBSTRING` cost is genuine (it's why the join step costs more CPU than
a plain insert) but isn't fixable by restructuring the join for
batch-scale loads like this one — it would matter more for
low-latency, single-row lookups (e.g., an interactive query resolving
one `trade_id_ref`), not bulk ingestion. Total measured load time for
~400,000 rows end to end: **~3.0 seconds** server-side — call it
~133,000 rows/sec on this host (SQL Server 2022 under x86 emulation on
Apple Silicon — see `sql/README.md`; a native deployment would likely be
faster, not measured here).

## Reproduce

```bash
python3 performance/generate_volume_dataset.py
python3 performance/generate_volume_synthetic.py
python3 performance/benchmark_matching_engine.py
# SQL load benchmark requires the container running; see sql/README.md
docker cp sql/perf_schema.sql reconengine-sql:/tmp/ && docker exec reconengine-sql /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P 'ReconEngine!2026' -C -d reconengine -i /tmp/perf_schema.sql
docker cp performance/volume_trades.csv reconengine-sql:/tmp/ && docker cp performance/volume_clearing_statements.csv reconengine-sql:/tmp/
docker cp sql/perf_load.sql reconengine-sql:/tmp/ && docker exec reconengine-sql /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P 'ReconEngine!2026' -C -d reconengine -i /tmp/perf_load.sql
```
