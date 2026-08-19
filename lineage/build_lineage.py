"""Step 12: writes the durable lineage graph (lineage/lineage_graph.json),
mirroring MarketForge's warehouse/metadata/lineage.json artifact (see
lineage/graph.py's docstring for the full reuse rationale), and loads the
same edges into the live `lineage_events` table.

Note on lineage_events' schema (sql/schema.sql, added in Step 2): its
source_pk/target_pk columns were designed for row-level lineage. This
step's edges are asset/table-level (matching the reused MarketForge
design), so source_pk/target_pk are populated as 0 -- an explicit
sentinel for "this edge describes the table-to-table relationship, not
one specific row" -- documented here rather than silently repurposing the
column's meaning.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib

from graph import EDGES, NODES

OUT_DIR = pathlib.Path(__file__).resolve().parent


def build_graph_json() -> dict:
    return {
        "generated_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
        "nodes": [
            {"table": n.table, "is_synthetic": n.is_synthetic, "description": n.description}
            for n in NODES.values()
        ],
        "edges": [
            {"source_table": e.source_table, "target_table": e.target_table,
             "transform_step": e.transform_step, "key_field": e.key_field}
            for e in EDGES
        ],
    }


def build_lineage_events_csv() -> None:
    rows = [
        {
            "source_table": e.source_table,
            "source_pk": 0,
            "target_table": e.target_table,
            "target_pk": 0,
            "transform_step": e.transform_step,
            "is_synthetic_source": NODES[e.source_table].is_synthetic,
        }
        for e in EDGES
    ]
    with (OUT_DIR / "lineage_events.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    graph = build_graph_json()
    (OUT_DIR / "lineage_graph.json").write_text(json.dumps(graph, indent=2) + "\n")
    build_lineage_events_csv()
    print(f"wrote {len(NODES)} nodes, {len(EDGES)} edges")


if __name__ == "__main__":
    main()
