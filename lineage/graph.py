"""Step 12: ReconEngine's lineage graph, at the same asset/table level of
granularity MarketForge's lineage design uses
(~/marketforge/docs/data_lineage.md, warehouse/lineage.py) -- nodes are
tables/CSV artifacts, edges are "this table was derived from that one, by
this script." That project explicitly scoped lineage to asset-level,
disclosing why: "this intentionally avoids maintaining a second SQL
parser or claiming column-level lineage." Reused here for the same
reason, not reinvented -- ReconEngine's pipeline is a fixed, known
sequence of ~10 transformation steps, not an arbitrary dbt DAG, so the
graph below is hand-defined rather than parsed from a manifest, but the
node/edge shape and the "durable JSON graph + ancestor-tracing CLI"
pattern (lineage/trace.py) are the same design MarketForge validated.

Row-level traceability -- the plan's "every dashboard figure traceable to
its originating record" -- is deliberately NOT pre-materialized as
millions of per-row lineage_events rows here (the same reasoning
MarketForge applied to column-level lineage: real, but not worth
maintaining a second mechanism for). Instead, lineage/trace.py walks this
graph and does the row lookup live, on demand, for one record at a time --
see that module.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Node:
    table: str
    is_synthetic: bool
    description: str


@dataclass(frozen=True)
class Edge:
    source_table: str
    target_table: str
    transform_step: str
    key_field: str  # the field used to join source rows to target rows, for trace.py


NODES: dict[str, Node] = {
    "trades_real.csv": Node("trades_real.csv", False, "real trades pulled live from venue APIs (Step 1)"),
    "trades": Node("trades", False, "real trades, ingested (Step 4)"),
    "clearing_statements": Node("clearing_statements", True, "synthetic, derived from trades (Step 2)"),
    "exchange_confirms": Node("exchange_confirms", True, "synthetic, derived from trades (Step 2)"),
    "lifecycle_events": Node("lifecycle_events", True, "derived from trades + synthetic records (Step 3); "
                              "timestamps are a mix of real (trades) and synthetic (clearing/confirm) inputs"),
    "settlements": Node("settlements", True, "derived from trades + lifecycle_events (Step 3)"),
    "accounting_feed": Node("accounting_feed", True, "derived from trades + lifecycle_events (Step 3)"),
    "reconciliation_results": Node("reconciliation_results", True, "derived from trades + clearing/confirm (Step 5)"),
    "root_cause_labels": Node("root_cause_labels", True, "derived from reconciliation_results + lifecycle_events (Step 6)"),
    "invoice_reconciliation": Node("invoice_reconciliation", True, "derived from trades + real fee schedules; "
                                     "actual_fee_usd side is synthetic (Step 9)"),
    "break_aging_daily": Node("break_aging_daily", True, "derived from root_cause_labels (Step 10)"),
    "break_aging_summary": Node("break_aging_summary", True, "derived from root_cause_labels (Step 10)"),
    "audit_log": Node("audit_log", True, "derived from ingestion_audit + break_aging_summary + invoice_reconciliation (Step 11)"),
}

EDGES: list[Edge] = [
    Edge("trades_real.csv", "trades", "ingestion/run_pipeline.py (Step 4)", "native_trade_id"),
    Edge("trades", "clearing_statements", "data/synthetic/generate_synthetic_records.py (Step 2)", "trade_id"),
    Edge("trades", "exchange_confirms", "data/synthetic/generate_synthetic_records.py (Step 2)", "trade_id"),
    Edge("trades", "lifecycle_events", "lifecycle/state_machine.py (Step 3)", "trade_id"),
    Edge("clearing_statements", "lifecycle_events", "lifecycle/state_machine.py (Step 3)", "trade_id"),
    Edge("exchange_confirms", "lifecycle_events", "lifecycle/state_machine.py (Step 3)", "trade_id"),
    Edge("lifecycle_events", "settlements", "lifecycle/state_machine.py (Step 3)", "trade_id"),
    Edge("lifecycle_events", "accounting_feed", "lifecycle/state_machine.py (Step 3)", "trade_id"),
    Edge("trades", "reconciliation_results", "reconciliation/matching_engine.py (Step 5)", "trade_id"),
    Edge("clearing_statements", "reconciliation_results", "reconciliation/matching_engine.py (Step 5)", "trade_id"),
    Edge("exchange_confirms", "reconciliation_results", "reconciliation/matching_engine.py (Step 5)", "trade_id"),
    Edge("reconciliation_results", "root_cause_labels", "root_cause/taxonomy.py (Step 6)", "trade_id"),
    Edge("lifecycle_events", "root_cause_labels", "root_cause/taxonomy.py (Step 6)", "trade_id"),
    Edge("trades", "invoice_reconciliation", "invoice_recon/generate_invoice.py (Step 9)", "trade_id"),
    Edge("root_cause_labels", "break_aging_daily", "aging/break_aging.py (Step 10)", "trade_id"),
    Edge("root_cause_labels", "break_aging_summary", "aging/break_aging.py (Step 10)", "trade_id"),
    Edge("break_aging_summary", "audit_log", "audit_trail/build_audit_log.py (Step 11)", "trade_id"),
    Edge("invoice_reconciliation", "audit_log", "audit_trail/build_audit_log.py (Step 11)", "trade_id"),
]


def ancestors(table: str) -> list[str]:
    """All tables `table` transitively depends on, nearest first."""
    visited: list[str] = []
    frontier = [table]
    seen = {table}
    while frontier:
        current = frontier.pop(0)
        parents = [e.source_table for e in EDGES if e.target_table == current]
        for p in parents:
            if p not in seen:
                seen.add(p)
                visited.append(p)
                frontier.append(p)
    return visited
