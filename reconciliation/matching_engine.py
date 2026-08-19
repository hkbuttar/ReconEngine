"""Step 5: matches real trades (data/real/trades_real.csv) against the two
synthetic external records (data/synthetic/{clearing_statements,exchange_confirms}.csv)
at each stage, classifying every (trade, stage) pair as matched, broken, or
missing -- plus a fuzzy composite-key pass over orphan records, per the
plan's "match on trade ID where available, fuzzy composite key otherwise."

Tolerances (disclosed judgment calls):
  - PRICE_TOLERANCE_PCT / QUANTITY_TOLERANCE_PCT = 0.01% relative
    difference. The clean ("none" break) synthetic rows are bit-exact
    copies of the real trade by construction (data/synthetic/generate_synthetic_records.py
    never perturbs them), so this tolerance's job here is to demonstrate
    the technique and guard defensively against float/rounding drift, not
    to rescue genuinely noisy real-world data -- it sits two orders of
    magnitude below the smallest injected mismatch (0.1%), so it cannot
    accidentally wave through a real break.
  - side has no tolerance concept -- any mismatch is a break.
  - Fuzzy matching (orphan records against still-unmatched real trades):
    same venue + symbol, timestamp within FUZZY_TIME_WINDOW, price/qty
    within FUZZY_TOLERANCE_PCT (much wider than the exact-match tolerance,
    since a fuzzy match is meant to catch "this might be the same trade
    under a corrupted key," not confirm a clean match).

Self-validation: because every synthetic row carries its true
`injected_break_type` (data/synthetic/README.md), this module also scores
its own matched/broken/missing calls against that ground truth -- a
concrete accuracy number, not just "it ran."
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib

REAL_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "real"
SYNTHETIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "synthetic"
OUT_DIR = pathlib.Path(__file__).resolve().parent

PRICE_TOLERANCE_PCT = 0.0001    # 0.01%
QUANTITY_TOLERANCE_PCT = 0.0001  # 0.01%

FUZZY_TIME_WINDOW = dt.timedelta(hours=1)
FUZZY_TOLERANCE_PCT = 0.05  # 5% -- wide, "plausibly the same trade" not "matches"


def _parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _rel_diff(a: float, b: float) -> float:
    if a == 0:
        return 0.0 if b == 0 else float("inf")
    return abs(a - b) / abs(a)


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def _index_by_ref(rows: list[dict]) -> dict[str, dict]:
    return {r["trade_id_ref"]: r for r in rows if r["trade_id_ref"]}


def classify_stage(trade: dict, synthetic_row: dict | None) -> dict:
    ref = f"{trade['venue']}:{trade['native_trade_id']}"
    if synthetic_row is None:
        return {"trade_id_ref": ref, "match_status": "missing", "price_diff_pct": "", "quantity_diff_pct": "", "side_match": "", "injected_break_type": ""}

    price_diff = _rel_diff(float(trade["price"]), float(synthetic_row["reported_price"]))
    qty_diff = _rel_diff(float(trade["quantity"]), float(synthetic_row["reported_quantity"]))
    side_match = trade["side"] == synthetic_row["reported_side"]

    is_matched = (
        price_diff <= PRICE_TOLERANCE_PCT
        and qty_diff <= QUANTITY_TOLERANCE_PCT
        and side_match
    )
    return {
        "trade_id_ref": ref,
        "match_status": "matched" if is_matched else "broken",
        "price_diff_pct": f"{price_diff * 100:.4f}",
        "quantity_diff_pct": f"{qty_diff * 100:.4f}",
        "side_match": side_match,
        "injected_break_type": synthetic_row["injected_break_type"],
    }


def fuzzy_match_orphans(missing_trades: list[dict], orphan_rows: list[dict], ref_col: str) -> list[dict]:
    """For each orphan synthetic record, look for a still-unmatched
    ('missing') real trade that's plausibly the same event under a
    corrupted key -- same venue+symbol, close in time, close in price/qty.
    Reports candidates found, doesn't merge/mutate anything upstream."""
    results = []
    for orphan in orphan_rows:
        orphan_price = float(orphan["reported_price"])
        orphan_qty = float(orphan["reported_quantity"])
        orphan_at = _parse_ts(orphan["received_at"])
        candidates = []
        for trade in missing_trades:
            if trade["venue"] != orphan["reported_venue"] or trade["symbol"] != orphan["reported_symbol"]:
                continue
            traded_at = _parse_ts(trade["traded_at"])
            if abs((traded_at - orphan_at).total_seconds()) > FUZZY_TIME_WINDOW.total_seconds():
                continue
            if _rel_diff(float(trade["price"]), orphan_price) > FUZZY_TOLERANCE_PCT:
                continue
            if _rel_diff(float(trade["quantity"]), orphan_qty) > FUZZY_TOLERANCE_PCT:
                continue
            candidates.append(f"{trade['venue']}:{trade['native_trade_id']}")
        results.append(
            {
                "orphan_ref": orphan[ref_col],
                "candidate_trade_refs": ";".join(candidates),
                "candidate_count": len(candidates),
            }
        )
    return results


def _write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def score_against_ground_truth(results: list[dict]) -> dict:
    """Confusion matrix: does match_status='matched' line up with
    injected_break_type='none', and match_status='broken' line up with a
    real injected break? (missing rows have no injected_break_type to
    score against here -- they're scored implicitly by definition: a row
    with no synthetic record can only ever be classified 'missing'.)

    `timing_breach` is excluded from this scoring, not treated as a
    false negative: it perturbs only the record's received_at timestamp,
    never price/quantity/side (data/synthetic/generate_synthetic_records.py),
    so this field-matching engine calling it 'matched' is the *correct*
    field-level verdict, not a miss -- timing correctness is a separate,
    already-covered concern (lifecycle/state_machine.py's on_time/late/
    breached status). Scoring it here as an error would conflate two
    genuinely different reconciliation questions.
    """
    tp = fp = tn = fn = 0
    for r in results:
        if r["match_status"] == "missing" or r["injected_break_type"] == "timing_breach":
            continue
        actually_clean = r["injected_break_type"] == "none"
        called_clean = r["match_status"] == "matched"
        if actually_clean and called_clean:
            tn += 1
        elif not actually_clean and not called_clean:
            tp += 1
        elif actually_clean and not called_clean:
            fp += 1
        else:
            fn += 1
    total = tp + fp + tn + fn
    accuracy = (tp + tn) / total if total else 0.0
    return {"true_positive_breaks": tp, "false_positive_breaks": fp, "true_negative_clean": tn,
            "false_negative_breaks": fn, "accuracy": round(accuracy, 4)}


def main() -> None:
    trades = _read_csv(REAL_DIR / "trades_real.csv")
    clearing_rows = _read_csv(SYNTHETIC_DIR / "clearing_statements.csv")
    confirm_rows = _read_csv(SYNTHETIC_DIR / "exchange_confirms.csv")

    clearing_by_ref = _index_by_ref(clearing_rows)
    confirm_by_ref = _index_by_ref(confirm_rows)

    clearing_results, confirm_results = [], []
    missing_clearing_trades, missing_confirm_trades = [], []

    for trade in trades:
        ref = f"{trade['venue']}:{trade['native_trade_id']}"

        c_result = classify_stage(trade, clearing_by_ref.get(ref))
        c_result["stage"] = "clearing"
        clearing_results.append(c_result)
        if c_result["match_status"] == "missing":
            missing_clearing_trades.append(trade)

        x_result = classify_stage(trade, confirm_by_ref.get(ref))
        x_result["stage"] = "confirm"
        confirm_results.append(x_result)
        if x_result["match_status"] == "missing":
            missing_confirm_trades.append(trade)

    orphan_clearing = [r for r in clearing_rows if not r["trade_id_ref"]]
    orphan_confirm = [r for r in confirm_rows if not r["trade_id_ref"]]
    fuzzy_clearing = fuzzy_match_orphans(missing_clearing_trades, orphan_clearing, "clearing_ref")
    fuzzy_confirm = fuzzy_match_orphans(missing_confirm_trades, orphan_confirm, "confirm_ref")

    all_results = clearing_results + confirm_results
    _write_csv(OUT_DIR / "reconciliation_results.csv", all_results)
    _write_csv(OUT_DIR / "fuzzy_match_clearing.csv", fuzzy_clearing)
    _write_csv(OUT_DIR / "fuzzy_match_confirm.csv", fuzzy_confirm)

    from collections import Counter

    summary = {
        "total_trades": len(trades),
        "clearing": {
            "status_counts": dict(Counter(r["match_status"] for r in clearing_results)),
            "ground_truth_score": score_against_ground_truth(clearing_results),
        },
        "confirm": {
            "status_counts": dict(Counter(r["match_status"] for r in confirm_results)),
            "ground_truth_score": score_against_ground_truth(confirm_results),
        },
        "fuzzy_matching": {
            "orphan_clearing_records": len(orphan_clearing),
            "orphan_clearing_with_candidates": sum(1 for r in fuzzy_clearing if r["candidate_count"] > 0),
            "orphan_confirm_records": len(orphan_confirm),
            "orphan_confirm_with_candidates": sum(1 for r in fuzzy_confirm if r["candidate_count"] > 0),
        },
    }
    import json

    (OUT_DIR / "generation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
