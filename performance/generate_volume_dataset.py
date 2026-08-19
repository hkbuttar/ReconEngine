"""Step 13: scales the real trade dataset (11,008 real trades, Step 1) up
to a realistic high-volume day for performance testing, via disclosed
replication -- not fabricated trades.

Technique: each replica trade copies a real trade's price, quantity, and
side verbatim (the actual real market data), gets a new synthetic
native_trade_id (the original id is real; the ID is what's synthesized,
since the real venue never issued a second id for the same trade), and
gets a new traded_at timestamp redistributed across a simulated 24-hour
trading day rather than the real ~7-minute capture window -- volume
scaling needs volume spread over time to be a meaningful throughput test,
not 200,000 trades all timestamped within the same 7 minutes.

This produces a SEPARATE dataset (performance/volume_trades.csv) --
it does not touch or replace data/real/trades_real.csv or anything
already loaded into the live schema. Performance testing runs against
its own tables (see performance/README.md), keeping the project's
primary real-data-anchored dataset untouched.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
import random

REAL_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "real"
OUT_DIR = pathlib.Path(__file__).resolve().parent

RANDOM_SEED = 42
TARGET_TRADE_COUNT = 200_000
SIMULATED_DAY = dt.date(2026, 8, 19)  # the real trade data's actual date


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def generate(real_trades: list[dict], target_count: int, rng: random.Random) -> list[dict]:
    replicas = []
    day_start = dt.datetime.combine(SIMULATED_DAY, dt.time.min, tzinfo=dt.timezone.utc)

    replica_index = 0
    while len(replicas) < target_count:
        source = real_trades[replica_index % len(real_trades)]
        generation = replica_index // len(real_trades)
        seconds_into_day = rng.uniform(0, 24 * 3600)
        replicas.append(
            {
                "venue": source["venue"],
                "native_trade_id": f"{source['native_trade_id']}-VOL{generation}",
                "symbol": source["symbol"],
                "side": source["side"],
                "price": source["price"],
                "quantity": source["quantity"],
                "traded_at": (day_start + dt.timedelta(seconds=seconds_into_day)).isoformat(),
            }
        )
        replica_index += 1

    replicas.sort(key=lambda r: r["traded_at"])
    return replicas


def main() -> None:
    real_trades = _read_csv(REAL_DIR / "trades_real.csv")
    rng = random.Random(RANDOM_SEED)

    volume_trades = generate(real_trades, TARGET_TRADE_COUNT, rng)

    with (OUT_DIR / "volume_trades.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(volume_trades[0].keys()))
        writer.writeheader()
        writer.writerows(volume_trades)

    summary = {
        "real_trades_source": len(real_trades),
        "target_count": target_count if (target_count := TARGET_TRADE_COUNT) else None,
        "generated_count": len(volume_trades),
        "replication_factor": round(len(volume_trades) / len(real_trades), 1),
        "simulated_day": SIMULATED_DAY.isoformat(),
    }
    import json

    (OUT_DIR / "volume_dataset_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
