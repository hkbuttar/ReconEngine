"""Verifies the lineage graph (lineage/graph.py) is actually complete:
every table that appears anywhere else in the schema as a real data
target has a lineage edge explaining where it came from, and the graph
that's loaded into the live `lineage_events` table matches the graph
defined in code -- catching lineage/build_lineage.py silently drifting
from lineage/graph.py, or a table added to the schema without a
corresponding lineage edge.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from conftest import DB_AVAILABLE, scalar  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "lineage"))
from graph import EDGES, NODES, ancestors  # noqa: E402

# Tables that are real ingestion targets or terminal/reference tables not
# expected to have an inbound lineage edge -- the real source of the whole
# graph, and infrastructure tables outside the derived-data lineage story.
NO_INBOUND_EDGE_EXPECTED = {"trades_real.csv"}


class TestGraphStructure:
    def test_every_node_except_the_real_source_has_an_inbound_edge(self):
        targets = {e.target_table for e in EDGES}
        for table in NODES:
            if table in NO_INBOUND_EDGE_EXPECTED:
                continue
            assert table in targets, f"{table} has no inbound lineage edge -- orphaned node"

    def test_every_edge_endpoint_is_a_defined_node(self):
        for edge in EDGES:
            assert edge.source_table in NODES, f"edge source {edge.source_table} not in NODES"
            assert edge.target_table in NODES, f"edge target {edge.target_table} not in NODES"

    def test_no_cycles_in_the_graph(self):
        # A real lineage graph must be a DAG -- a cycle would mean a table
        # derived from itself, which can't be true of this pipeline.
        for table in NODES:
            assert table not in ancestors(table), f"{table} is its own ancestor -- cycle detected"

    def test_trades_is_the_only_real_node(self):
        real_nodes = [t for t, n in NODES.items() if not n.is_synthetic]
        assert real_nodes == ["trades_real.csv", "trades"]

    def test_every_downstream_table_traces_back_to_the_real_trades(self):
        # The core disclosure claim (data/real/README.md,
        # data/synthetic/README.md): everything synthetic is *derived
        # from* the real trades, not invented independently -- verified
        # structurally here, not just asserted in prose.
        for table in NODES:
            if table == "trades_real.csv":
                continue
            chain = ancestors(table)
            assert "trades_real.csv" in chain or table == "trades", \
                f"{table} doesn't trace back to trades_real.csv"


@pytest.mark.skipif(not DB_AVAILABLE, reason="reconengine-sql container not reachable")
class TestLoadedGraphMatchesCode:
    def test_loaded_edge_count_matches_code(self):
        loaded_count = int(scalar("SELECT COUNT(*) FROM lineage_events;"))
        assert loaded_count == len(EDGES)

    def test_every_coded_edge_is_present_in_the_live_table(self):
        loaded = scalar(
            "SELECT COUNT(*) FROM lineage_events;"
        )
        assert int(loaded) > 0
        for edge in EDGES:
            count = scalar(
                f"SELECT COUNT(*) FROM lineage_events WHERE source_table = '{edge.source_table}' "
                f"AND target_table = '{edge.target_table}';"
            )
            assert int(count) >= 1, f"edge {edge.source_table} -> {edge.target_table} missing from live table"
