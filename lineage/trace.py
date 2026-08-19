"""Step 12: traces one specific trade's actual data through every table
it appears in, live, on demand -- the "every dashboard figure traceable
to its originating record" requirement, satisfied by walking
lineage/graph.py's asset-level graph and looking up the real row at each
hop, rather than pre-materializing a row-level lineage table for millions
of rows (see graph.py's docstring for why that's a deliberate, reused
scope decision, not an oversight).

Usage: python3 lineage/trace.py <venue>:<native_trade_id>
"""

from __future__ import annotations

import csv
import pathlib
import sys

from graph import NODES

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

TABLE_SOURCES: dict[str, pathlib.Path] = {
    "trades_real.csv": REPO_ROOT / "data" / "real" / "trades_real.csv",
    "clearing_statements": REPO_ROOT / "data" / "synthetic" / "clearing_statements.csv",
    "exchange_confirms": REPO_ROOT / "data" / "synthetic" / "exchange_confirms.csv",
    "lifecycle_events": REPO_ROOT / "lifecycle" / "lifecycle_events.csv",
    "settlements": REPO_ROOT / "lifecycle" / "settlements.csv",
    "accounting_feed": REPO_ROOT / "lifecycle" / "accounting_feed.csv",
    "reconciliation_results": REPO_ROOT / "reconciliation" / "reconciliation_results.csv",
    "root_cause_labels": REPO_ROOT / "root_cause" / "root_cause_labels.csv",
    "invoice_reconciliation": REPO_ROOT / "invoice_recon" / "invoice_reconciliation.csv",
    "break_aging_summary": REPO_ROOT / "aging" / "break_aging_summary.csv",
}

REF_FIELD_BY_TABLE = {
    "trades_real.csv": None,  # composite venue+native_trade_id, handled specially
    "clearing_statements": "trade_id_ref",
    "exchange_confirms": "trade_id_ref",
    "lifecycle_events": "trade_id_ref",
    "settlements": "trade_id_ref",
    "accounting_feed": "trade_id_ref",
    "reconciliation_results": "trade_id_ref",
    "root_cause_labels": "trade_id_ref",
    "invoice_reconciliation": "trade_id_ref",
    "break_aging_summary": "trade_id_ref",
}


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def find_rows(table: str, trade_ref: str) -> list[dict]:
    path = TABLE_SOURCES.get(table)
    if path is None or not path.exists():
        return []
    rows = _read_csv(path)
    if table == "trades_real.csv":
        venue, native_id = trade_ref.split(":", 1)
        return [r for r in rows if r["venue"] == venue and r["native_trade_id"] == native_id]
    ref_field = REF_FIELD_BY_TABLE[table]
    return [r for r in rows if r.get(ref_field) == trade_ref]


def trace(trade_ref: str) -> None:
    print(f"=== Lineage trace for {trade_ref} ===\n")

    for table in ["trades_real.csv"] + list(TABLE_SOURCES.keys())[1:]:
        node = NODES.get(table)
        rows = find_rows(table, trade_ref)
        real_tag = "SYNTHETIC" if node and node.is_synthetic else "REAL"
        if not rows:
            print(f"[{real_tag}] {table}: no row (gated out upstream, or not yet reached)")
            continue
        print(f"[{real_tag}] {table}: {len(rows)} row(s)")
        for row in rows:
            interesting = {k: v for k, v in row.items() if k not in ("trade_id_ref",)}
            print(f"    {interesting}")
        print(f"    -- {node.description if node else ''}")


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: trace.py <venue>:<native_trade_id>")
        raise SystemExit(1)
    trace(sys.argv[1])


if __name__ == "__main__":
    main()
