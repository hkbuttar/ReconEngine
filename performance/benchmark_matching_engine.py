"""Step 13: measures the real matching engine's (reconciliation/matching_engine.py)
throughput and latency against the volume-scaled dataset -- the actual
pipeline code, not a stand-in benchmark that merely resembles it.
"""

from __future__ import annotations

import csv
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "reconciliation"))
from matching_engine import classify_stage  # noqa: E402

OUT_DIR = pathlib.Path(__file__).resolve().parent


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def _index_by_ref(rows: list[dict]) -> dict[str, dict]:
    return {r["trade_id_ref"]: r for r in rows if r["trade_id_ref"]}


def main() -> None:
    load_start = time.perf_counter()
    trades = _read_csv(OUT_DIR / "volume_trades.csv")
    clearing_rows = _read_csv(OUT_DIR / "volume_clearing_statements.csv")
    confirm_rows = _read_csv(OUT_DIR / "volume_exchange_confirms.csv")
    load_elapsed = time.perf_counter() - load_start

    index_start = time.perf_counter()
    clearing_by_ref = _index_by_ref(clearing_rows)
    confirm_by_ref = _index_by_ref(confirm_rows)
    index_elapsed = time.perf_counter() - index_start

    match_start = time.perf_counter()
    results = []
    for trade in trades:
        ref = f"{trade['venue']}:{trade['native_trade_id']}"
        results.append(classify_stage(trade, clearing_by_ref.get(ref)))
        results.append(classify_stage(trade, confirm_by_ref.get(ref)))
    match_elapsed = time.perf_counter() - match_start

    n_trades = len(trades)
    n_classifications = len(results)
    throughput_trades_per_sec = n_trades / match_elapsed
    throughput_classifications_per_sec = n_classifications / match_elapsed

    summary = {
        "n_trades": n_trades,
        "n_classifications": n_classifications,
        "csv_load_seconds": round(load_elapsed, 4),
        "index_build_seconds": round(index_elapsed, 4),
        "matching_seconds": round(match_elapsed, 4),
        "throughput_trades_per_sec": round(throughput_trades_per_sec, 1),
        "throughput_classifications_per_sec": round(throughput_classifications_per_sec, 1),
        "extrapolated_capacity_trades_per_day": round(throughput_trades_per_sec * 86400),
        "extrapolated_capacity_trades_per_day_millions": round(throughput_trades_per_sec * 86400 / 1_000_000, 1),
    }
    import json

    (OUT_DIR / "matching_engine_benchmark.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
