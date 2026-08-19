"""Step 13: generates clearing/confirm records for the volume-scaled
trade dataset (volume_trades.csv), reusing Step 2's actual
generate_synthetic_records.generate() function against the larger input
rather than duplicating the break-injection logic -- same disclosed
discrepancy rates and methodology, just at volume.
"""

from __future__ import annotations

import csv
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "data" / "synthetic"))
from generate_synthetic_records import RANDOM_SEED, generate  # noqa: E402

OUT_DIR = pathlib.Path(__file__).resolve().parent


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def _write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    trades = _read_csv(OUT_DIR / "volume_trades.csv")
    rng = random.Random(RANDOM_SEED)

    clearing_rows = generate("clearing", trades, rng)
    confirm_rows = generate("confirm", trades, rng)

    _write_csv(OUT_DIR / "volume_clearing_statements.csv", clearing_rows)
    _write_csv(OUT_DIR / "volume_exchange_confirms.csv", confirm_rows)

    print(f"clearing: {len(clearing_rows)} rows, confirm: {len(confirm_rows)} rows")


if __name__ == "__main__":
    main()
