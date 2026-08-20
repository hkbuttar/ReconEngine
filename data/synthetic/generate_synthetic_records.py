"""Derives synthetic clearing_statements and exchange_confirms records from
data/real/trades_real.csv, with disclosed, labeled discrepancies injected
into a fixed fraction of trades.

This is the one place in the project where synthetic data is generated --
see data/synthetic/README.md for the full disclosure. Every row this script
writes carries an `injected_break_type` column (`'none'` for a clean
match) so the synthetic layer is auditable at a glance rather than needing
to be reverse-engineered later. This also doubles as ground truth for
rule-based vs. ML root-cause classifier comparison.

Deterministic: fixed random seed (42), so reruns reproduce the same
injected breaks against the same real trades_real.csv. Re-run after a
fresh `ingestion/acquire_real_trades.py` pull to regenerate against new
real trades.

Injection design (disclosed judgment call -- see module-level BREAK_RATES
below for exact per-category rates, chosen to be large enough to give the
downstream reconciliation engine and classifiers
meaningfully many examples of each break type without making "broken" the
common case, which would misrepresent how reconciliation actually looks in
practice -- most trades match cleanly):

  - missing: no synthetic record generated for that stage at all -- the
    real trade exists, nothing downstream reports it. Which stage is
    implicit from which file the (absence of a) row would be in.
  - orphan: a synthetic record generated with NO matching real trade --
    the clearing firm/exchange reports something the front office never
    captured. A plausible fake trade is synthesized for this (price/qty in
    a realistic real-trade's neighborhood at a random real timestamp)
    since there is, by definition, no real trade to derive it from.
  - price_mismatch: reported price perturbed by a random 0.1%-2% delta.
  - quantity_mismatch: reported quantity perturbed similarly.
  - side_mismatch: reported side flipped (buy<->sell).
  - timing_breach: received_at/confirm_timestamp pushed well past the
    normal processing lag (see PROCESSING_LAG below), simulating a delayed
    clearing/confirm feed.

Normal (non-broken) processing lag is itself a disclosed judgment call,
not a cited industry SLA: clearing statements are modeled as received
same-day within a few hours of the trade; exchange confirms within
minutes. These are illustrative, not sourced figures -- flagged here
rather than presented as fact.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
import random

REAL_TRADES_PATH = pathlib.Path(__file__).resolve().parent.parent / "real" / "trades_real.csv"
OUT_DIR = pathlib.Path(__file__).resolve().parent

RANDOM_SEED = 42

# Fraction of real trades receiving each injected break, applied
# independently per stage (clearing vs. confirm). Sums to 12% of real
# trades per stage; the remaining 88% match cleanly. An additional 1% of
# trade-count orphan records (ORPHAN_RATE, below) are layered on top per
# stage, with no real trade behind them at all -- so ~13% of rows per
# stage carry a disclosed injected break. Disclosed judgment call -- see
# module docstring.
BREAK_RATES = {
    "missing": 0.02,
    "price_mismatch": 0.03,
    "quantity_mismatch": 0.03,
    "timing_breach": 0.03,
    "side_mismatch": 0.01,
}
ORPHAN_RATE = 0.01  # extra orphan records, on top of the real-trade-keyed rows above

CLEARING_LAG = (dt.timedelta(minutes=30), dt.timedelta(hours=6))
CONFIRM_LAG = (dt.timedelta(seconds=5), dt.timedelta(minutes=15))
TIMING_BREACH_LAG = (dt.timedelta(days=1), dt.timedelta(days=3))


def _read_real_trades() -> list[dict]:
    with REAL_TRADES_PATH.open() as f:
        return list(csv.DictReader(f))


def _pick_break(rng: random.Random) -> str:
    roll = rng.random()
    cumulative = 0.0
    for break_type, rate in BREAK_RATES.items():
        cumulative += rate
        if roll < cumulative:
            return break_type
    return "none"


def _perturb_price(price: float, rng: random.Random) -> float:
    pct = rng.uniform(0.001, 0.02) * rng.choice([-1, 1])
    return round(price * (1 + pct), 8)


def _perturb_quantity(quantity: float, rng: random.Random) -> float:
    pct = rng.uniform(0.001, 0.02) * rng.choice([-1, 1])
    perturbed = round(max(quantity * (1 + pct), 1e-8), 8)
    if perturbed == round(quantity, 8):
        # Crypto quantities can already sit at the 1e-8 floor (the
        # smallest representable unit at this precision) -- a 0.1-2%
        # relative perturbation of such a value rounds back to the exact
        # same 8-decimal figure, silently no-op'ing the injected break.
        # Force a minimal but real, observable difference instead.
        direction = 1 if pct >= 0 else -1
        perturbed = round(quantity, 8) + direction * 1e-8
        if perturbed <= 0:
            perturbed = quantity + 1e-8
    return round(perturbed, 8)


def _flip_side(side: str) -> str:
    return "sell" if side == "buy" else "buy"


def _build_synthetic_row(
    trade: dict,
    rng: random.Random,
    ref_prefix: str,
    lag_range: tuple[dt.timedelta, dt.timedelta],
    timestamp_field: str,
) -> dict | None:
    # `break_type` values ("missing", "orphan", ...) are stage-agnostic by
    # design: which stage a break applies to is implicit from which CSV
    # (clearing_statements.csv vs exchange_confirms.csv) the row lands in.
    break_type = _pick_break(rng)
    traded_at = dt.datetime.fromisoformat(trade["traded_at"].replace("Z", "+00:00"))

    if break_type == "missing":
        return None

    price = float(trade["price"])
    quantity = float(trade["quantity"])
    side = trade["side"]

    if break_type == "price_mismatch":
        price = _perturb_price(price, rng)
    elif break_type == "quantity_mismatch":
        quantity = _perturb_quantity(quantity, rng)
    elif break_type == "side_mismatch":
        side = _flip_side(side)

    lag_low, lag_high = lag_range
    lag_seconds = rng.uniform(lag_low.total_seconds(), lag_high.total_seconds())
    if break_type == "timing_breach":
        breach_low, breach_high = TIMING_BREACH_LAG
        lag_seconds = rng.uniform(breach_low.total_seconds(), breach_high.total_seconds())
    received_at = traded_at + dt.timedelta(seconds=lag_seconds)

    return {
        "trade_id_ref": f"{trade['venue']}:{trade['native_trade_id']}",
        f"{ref_prefix}_ref": f"{ref_prefix.upper()}-{trade['venue'][:3].upper()}-{trade['native_trade_id']}",
        "reported_venue": trade["venue"],
        "reported_symbol": trade["symbol"],
        "reported_side": side,
        "reported_price": f"{price:.8f}",
        "reported_quantity": f"{quantity:.8f}",
        timestamp_field: received_at.isoformat(),
        "received_at": received_at.isoformat(),
        "is_synthetic": 1,
        "injected_break_type": break_type,
    }


def _build_orphan_row(
    sample_trade: dict,
    rng: random.Random,
    index: int,
    ref_prefix: str,
    timestamp_field: str,
) -> dict:
    """An orphan record has no real trade behind it by definition -- its
    price/quantity/timestamp are synthesized in the neighborhood of a real
    sample trade's values rather than fabricated from nothing, and it is
    unambiguously flagged via trade_id_ref='' (no real trade to reference)."""
    traded_at = dt.datetime.fromisoformat(sample_trade["traded_at"].replace("Z", "+00:00"))
    jittered_at = traded_at + dt.timedelta(minutes=rng.uniform(-60, 60))
    return {
        "trade_id_ref": "",
        f"{ref_prefix}_ref": f"{ref_prefix.upper()}-ORPHAN-{index:06d}",
        "reported_venue": sample_trade["venue"],
        "reported_symbol": sample_trade["symbol"],
        "reported_side": rng.choice(["buy", "sell"]),
        "reported_price": f"{_perturb_price(float(sample_trade['price']), rng):.8f}",
        "reported_quantity": f"{_perturb_quantity(float(sample_trade['quantity']), rng):.8f}",
        timestamp_field: jittered_at.isoformat(),
        "received_at": jittered_at.isoformat(),
        "is_synthetic": 1,
        "injected_break_type": "orphan",
    }


def generate(stage: str, trades: list[dict], rng: random.Random) -> list[dict]:
    ref_prefix = "clearing" if stage == "clearing" else "confirm"
    timestamp_field = "statement_date" if stage == "clearing" else "confirm_timestamp"
    lag_range = CLEARING_LAG if stage == "clearing" else CONFIRM_LAG

    rows: list[dict] = []
    for trade in trades:
        row = _build_synthetic_row(trade, rng, ref_prefix, lag_range, timestamp_field)
        if row is not None:
            if stage == "clearing":
                row["statement_date"] = row["statement_date"][:10]
            rows.append(row)

    n_orphans = int(len(trades) * ORPHAN_RATE)
    for i in range(n_orphans):
        sample_trade = rng.choice(trades)
        row = _build_orphan_row(sample_trade, rng, i, ref_prefix, timestamp_field)
        if stage == "clearing":
            row["statement_date"] = row["statement_date"][:10]
        rows.append(row)

    return rows


def _write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    trades = _read_real_trades()
    rng = random.Random(RANDOM_SEED)

    clearing_rows = generate("clearing", trades, rng)
    confirm_rows = generate("confirm", trades, rng)

    _write_csv(OUT_DIR / "clearing_statements.csv", clearing_rows)
    _write_csv(OUT_DIR / "exchange_confirms.csv", confirm_rows)

    from collections import Counter

    summary = {
        "real_trades": len(trades),
        "clearing_statements": {
            "total_rows": len(clearing_rows),
            "by_break_type": dict(Counter(r["injected_break_type"] for r in clearing_rows)),
        },
        "exchange_confirms": {
            "total_rows": len(confirm_rows),
            "by_break_type": dict(Counter(r["injected_break_type"] for r in confirm_rows)),
        },
    }
    import json

    (OUT_DIR / "generation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
