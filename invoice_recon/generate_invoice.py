"""Step 9: computes EXPECTED invoice line items from real trade volume
against Step 1's real, published fee schedules (data/real/fee_schedules.py),
then generates a synthetically perturbed "actual received invoice" per
venue with disclosed, labeled discrepancies -- the discrepancy itself,
not the underlying real fee rates, is what's unavoidably synthetic (no
public source publishes a firm's actual invoice-vs-expected mismatches,
same reasoning as data/synthetic/README.md's clearing/confirm layer).

Every real trade is billed as a taker fill (data/real/fee_schedules.py's
disclosed simplification: public trade tape only shows the aggressor
side). Settlement currency is USD for all three venues, including
Binance's USDT-quoted pair, matching lifecycle/state_machine.py's
already-disclosed 1:1 USDT/USD simplification.

Discrepancy types (disclosed judgment call -- rates below):
  - double_billed: the exchange's invoice charges the expected fee twice.
  - rate_misapplied: the invoice applies a materially different bps rate
    than the venue's real published taker rate (a stale tier, a wrong
    venue's rate, etc.) -- not a rounding difference, a genuinely wrong
    rate.
  - missing_line: the trade has no invoice line at all -- the firm was
    undercharged (in disclosure, not in the firm's favor to hide: an
    under-bill is still a reconciliation break worth catching).
  - rounding_error: a small, consistent sub-cent rounding difference --
    included specifically to exercise a materiality threshold (see
    reconcile_invoice()'s MATERIALITY_THRESHOLD_USD), not just an
    equality check. A real invoice reconciliation tolerates rounding
    noise; it should not tolerate a misapplied rate of the same rough
    magnitude, so this project deliberately keeps rounding tiny (sub-cent)
    and rate misapplication large (>=20% off) rather than letting them
    blur together.

Disclosed omission: the plan's illustrative list of invoice discrepancy
types also mentions "missing rebates." This project's fill model bills
every trade as a taker (no maker fills, per the fee-schedule module's
disclosed limitation), and Binance's own maker fee is 0% -- there is no
real rebate structure in play here to mis-omit, so this category is left
out rather than fabricated to fit the plan's example list.
"""

from __future__ import annotations

import csv
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from data.real.fee_schedules import VENUE_FEE_SCHEDULES  # noqa: E402

REAL_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "real"
OUT_DIR = pathlib.Path(__file__).resolve().parent

RANDOM_SEED = 42

# Fraction of trades receiving each injected discrepancy on the "actual"
# invoice; remainder billed correctly. Disclosed judgment call -- same
# design philosophy as data/synthetic/generate_synthetic_records.py's
# BREAK_RATES (large enough to exercise every category, not so large that
# "wrong" becomes the common case).
DISCREPANCY_RATES = {
    "double_billed": 0.02,
    "rate_misapplied": 0.02,
    "missing_line": 0.02,
    "rounding_error": 0.03,
}

MATERIALITY_THRESHOLD_USD = 0.01  # sub-cent differences are not flagged as breaks
MATERIALITY_THRESHOLD_PCT = 0.10  # ...unless they're >10% of the expected fee itself


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def _fixed(value: float) -> str:
    """Fixed-point string, never scientific notation -- str(round(x, 8))
    silently produces '1e-08' for very small fee/notional amounts (some
    crypto trades here have sub-cent fees), which SQL Server's BULK
    INSERT + CAST(... AS DECIMAL) rejects. Same fix as
    data/synthetic/generate_synthetic_records.py's _perturb_quantity."""
    return f"{value:.8f}"


def compute_expected_line(trade: dict) -> dict:
    schedule = VENUE_FEE_SCHEDULES[trade["venue"]]
    notional = float(trade["price"]) * float(trade["quantity"])
    expected_fee = notional * schedule.taker_fee_bps / 10_000
    return {
        "trade_id_ref": f"{trade['venue']}:{trade['native_trade_id']}",
        "venue": trade["venue"],
        "notional": _fixed(notional),
        "taker_fee_bps_applied": schedule.taker_fee_bps,
        "expected_fee_usd": _fixed(expected_fee),
    }


def _pick_discrepancy(rng: random.Random) -> str:
    roll = rng.random()
    cumulative = 0.0
    for kind, rate in DISCREPANCY_RATES.items():
        cumulative += rate
        if roll < cumulative:
            return kind
    return "none"


def generate_actual_line(expected: dict, rng: random.Random) -> dict | None:
    discrepancy = _pick_discrepancy(rng)
    expected_fee = float(expected["expected_fee_usd"])
    notional = float(expected["notional"])

    if discrepancy == "missing_line":
        return None
    if discrepancy == "double_billed":
        actual_fee = expected_fee * 2
    elif discrepancy == "rate_misapplied":
        real_bps = VENUE_FEE_SCHEDULES[expected["venue"]].taker_fee_bps
        wrong_bps = max(real_bps + real_bps * rng.uniform(0.3, 0.7) * rng.choice([-1, 1]), 0.1)
        actual_fee = notional * wrong_bps / 10_000
    elif discrepancy == "rounding_error":
        actual_fee = expected_fee + rng.uniform(-0.005, 0.005)
    else:
        actual_fee = expected_fee

    return {
        "trade_id_ref": expected["trade_id_ref"],
        "venue": expected["venue"],
        "actual_fee_usd": _fixed(actual_fee),
        "injected_discrepancy_type": discrepancy,
    }


def reconcile_invoice(expected_rows: list[dict], actual_by_ref: dict[str, dict]) -> list[dict]:
    reconciled = []
    for expected in expected_rows:
        ref = expected["trade_id_ref"]
        actual = actual_by_ref.get(ref)
        if actual is None:
            reconciled.append(
                {**expected, "actual_fee_usd": None, "delta_usd": None,
                 "match_status": "missing", "injected_discrepancy_type": "missing_line"}
            )
            continue
        actual_fee = float(actual["actual_fee_usd"])
        expected_fee = float(expected["expected_fee_usd"])
        delta = actual_fee - expected_fee
        rel_diff = abs(delta) / expected_fee if expected_fee > 0 else (0.0 if delta == 0 else float("inf"))
        # A fixed-dollar threshold alone lets large *relative* errors (e.g. a
        # doubled fee) slip through unflagged on tiny-notional trades, where
        # even 2x the expected fee is still a few cents. Flagged as material
        # if it fails either test -- not just the absolute one.
        is_immaterial = abs(delta) <= MATERIALITY_THRESHOLD_USD and rel_diff <= MATERIALITY_THRESHOLD_PCT
        match_status = "matched" if is_immaterial else "discrepant"
        reconciled.append(
            {**expected, "actual_fee_usd": actual["actual_fee_usd"], "delta_usd": _fixed(delta),
             "match_status": match_status, "injected_discrepancy_type": actual["injected_discrepancy_type"]}
        )
    return reconciled


def _write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    trades = _read_csv(REAL_DIR / "trades_real.csv")
    rng = random.Random(RANDOM_SEED)

    expected_rows = [compute_expected_line(t) for t in trades]
    actual_rows = []
    for expected in expected_rows:
        actual = generate_actual_line(expected, rng)
        if actual is not None:
            actual_rows.append(actual)
    actual_by_ref = {a["trade_id_ref"]: a for a in actual_rows}

    reconciled = reconcile_invoice(expected_rows, actual_by_ref)

    _write_csv(OUT_DIR / "expected_invoice_lines.csv", expected_rows)
    _write_csv(OUT_DIR / "actual_invoice_lines.csv", actual_rows)
    _write_csv(OUT_DIR / "invoice_reconciliation.csv", reconciled)

    from collections import Counter, defaultdict

    by_status = Counter(r["match_status"] for r in reconciled)
    by_discrepancy = Counter(r["injected_discrepancy_type"] for r in reconciled)

    venue_summary = defaultdict(lambda: {"expected_total_usd": 0.0, "actual_total_usd": 0.0, "trade_count": 0, "discrepant_count": 0})
    for r in reconciled:
        v = venue_summary[r["venue"]]
        v["trade_count"] += 1
        v["expected_total_usd"] += float(r["expected_fee_usd"])
        v["actual_total_usd"] += float(r["actual_fee_usd"]) if r["actual_fee_usd"] else 0.0
        if r["match_status"] != "matched":
            v["discrepant_count"] += 1
    for v in venue_summary.values():
        v["expected_total_usd"] = round(v["expected_total_usd"], 2)
        v["actual_total_usd"] = round(v["actual_total_usd"], 2)
        v["net_delta_usd"] = round(v["actual_total_usd"] - v["expected_total_usd"], 2)

    summary = {
        "total_trades": len(trades),
        "match_status_counts": dict(by_status),
        "discrepancy_type_counts": dict(by_discrepancy),
        "materiality_threshold_usd": MATERIALITY_THRESHOLD_USD,
        "venue_summary": dict(venue_summary),
    }
    import json

    (OUT_DIR / "generation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
