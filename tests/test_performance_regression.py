"""Performance regression test against the recorded baseline
(performance/matching_engine_benchmark.json, 452,610 trades/sec on this
host). Self-contained: generates its own in-memory synthetic trade/
reported-record pairs rather than depending on the large, gitignored
performance/volume_*.csv files (performance/README.md) -- keeps this test
fast and runnable without regenerating multi-hundred-MB files first.

Threshold is deliberately generous (20% of baseline, not "any slowdown at
all"): the goal is catching an actual regression (e.g. an accidentally
introduced O(n^2) pattern, which would show up as an order-of-magnitude
drop), not failing on ordinary machine-load variance between runs.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "reconciliation"))
from matching_engine import classify_stage  # noqa: E402

BASELINE_PATH = pathlib.Path(__file__).resolve().parent.parent / "performance" / "matching_engine_benchmark.json"
REGRESSION_THRESHOLD_FRACTION = 0.20  # fail only if throughput drops below 20% of the recorded baseline
N_SYNTHETIC_PAIRS = 50_000


def _generate_pairs(n: int) -> list[tuple[dict, dict]]:
    pairs = []
    for i in range(n):
        trade = {"venue": "test", "native_trade_id": str(i), "price": "68000.00000000",
                  "quantity": "0.01000000", "side": "buy"}
        synthetic = {"reported_price": "68000.00000000", "reported_quantity": "0.01000000",
                     "reported_side": "buy", "injected_break_type": "none"}
        pairs.append((trade, synthetic))
    return pairs


class TestMatchingEngineThroughputRegression:
    def test_baseline_file_exists_and_is_readable(self):
        assert BASELINE_PATH.exists(), "no recorded baseline -- run performance/benchmark_matching_engine.py first"
        baseline = json.loads(BASELINE_PATH.read_text())
        assert baseline["throughput_trades_per_sec"] > 0

    def test_current_throughput_is_not_a_severe_regression(self):
        baseline = json.loads(BASELINE_PATH.read_text())
        baseline_throughput = baseline["throughput_trades_per_sec"]
        minimum_acceptable = baseline_throughput * REGRESSION_THRESHOLD_FRACTION

        pairs = _generate_pairs(N_SYNTHETIC_PAIRS)
        start = time.perf_counter()
        for trade, synthetic in pairs:
            classify_stage(trade, synthetic)
        elapsed = time.perf_counter() - start

        current_throughput = N_SYNTHETIC_PAIRS / elapsed
        assert current_throughput >= minimum_acceptable, (
            f"matching engine throughput {current_throughput:.0f} trades/sec is below "
            f"{REGRESSION_THRESHOLD_FRACTION:.0%} of the recorded baseline "
            f"({baseline_throughput:.0f} trades/sec) -- possible performance regression"
        )
