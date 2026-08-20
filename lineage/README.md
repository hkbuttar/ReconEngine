# lineage/ — Data Lineage Tracking

Two complementary pieces, both explicitly reusing the design MarketForge
already validated (`~/marketforge/docs/data_lineage.md`,
`warehouse/lineage.py`) rather than reinventing lineage tracking from
scratch — see `graph.py`'s docstring for the full reuse rationale.

## 1. Asset-level graph (`graph.py`, `build_lineage.py`)

13 nodes (tables/CSV artifacts), 18 edges (which script derived which
table from which). Same shape as MarketForge's `lineage.json`: durable
JSON export (`lineage_graph.json`) plus the same rows loaded into
`lineage_events` for SQL-side querying. **Deliberately table-level, not
row-level** — the same scope decision MarketForge made for column-level
lineage, disclosed there as "avoids maintaining a second SQL parser," and
reused here for the same reason: ReconEngine's pipeline is a fixed,
known sequence of ~10 steps, not a large arbitrary DAG, so a hand-defined
graph is more honest and maintainable than fabricating row-level lineage
rows for tens of thousands of records.

Every node is tagged `is_synthetic` — real: `trades_real.csv`/`trades`;
everything downstream of a synthetic input inherits that tag at the edge
level, so a table like `lifecycle_events` (which blends real `trades`
timestamps with synthetic `clearing_statements`/`exchange_confirms`
timestamps) correctly shows **both** a real-sourced edge and a
synthetic-sourced edge into it, rather than being labeled one or the
other.

## 2. Record-level trace, on demand (`trace.py`)

The plan's actual requirement — "every dashboard figure traceable to its
originating record" — needs row-level detail, which the asset graph
above deliberately doesn't pre-materialize. `trace.py` closes that gap by
walking the graph and looking up one trade's **real row data** at every
hop, live:

```bash
python3 lineage/trace.py kraken:105347918
```

Live-tested output (abridged) for a trade with an aged, unresolved
`QUANTITY` break on the clearing side and a same-day-resolved `TIMING`
issue on the confirm side — a genuinely coherent story across 10 tables,
not manufactured for the demo:

```
[REAL] trades_real.csv: price=68550.10000, quantity=0.01144325
[SYNTHETIC] clearing_statements: reported_quantity=0.01130479, injected_break_type=quantity_mismatch
[SYNTHETIC] exchange_confirms: injected_break_type=timing_breach
[SYNTHETIC] reconciliation_results: clearing → broken (quantity_diff_pct=1.21%); confirm → matched
[SYNTHETIC] root_cause_labels: clearing → QUANTITY; confirm → TIMING (has_timing_issue=True)
[SYNTHETIC] break_aging_summary: clearing → still_open, TIER4_CRITICAL_AGED; confirm → resolved same day
```

Every number in that chain is internally consistent end to end — the
quantity break traced from the real trade's actual quantity through the
synthetic clearing statement's perturbed value, into the matching
engine's computed diff, into the taxonomy label, into its final aging
outcome.
