"""Rule-based half: predicts root_cause_category from observable
fields only -- price_diff_pct, quantity_diff_pct, side_match, match_status,
lifecycle_status -- the same signals a real reconciliation analyst would
actually see. Deliberately does NOT read `injected_break_type`; that
column exists only in root_cause_labels.csv as the ground truth this
module is scored against, exactly as scored the matching engine and
scored the taxonomy crosswalk against it.

This is functionally a hand-written decision tree mirroring how a real
ops rule engine would triage a break -- see root_cause/taxonomy.py's
priority rule (MISSING_RECORD > REFERENCE_DATA > QUANTITY > PRICING >
TIMING > CLEAN), reproduced here using only observable signals instead of
the injected label. The two are expected to agree closely: this project's
synthetic breaks are deterministic and mutually exclusive by construction
(data/synthetic/generate_synthetic_records.py), so there's little hidden
signal for a purely rule-based approach to miss on this dataset -- see
root_cause/README.md's comparison section for the honest framing of what
that does and doesn't prove about rules vs. ML in general.

Tolerance: reuses reconciliation/matching_engine.py's PRICE_TOLERANCE_PCT
/ QUANTITY_TOLERANCE_PCT (0.01%) for consistency -- the diff_pct fields
here are exactly that engine's output.
"""

from __future__ import annotations

import csv
import pathlib

RECONCILIATION_DIR = pathlib.Path(__file__).resolve().parent.parent / "reconciliation"
LIFECYCLE_DIR = pathlib.Path(__file__).resolve().parent.parent / "lifecycle"
OUT_DIR = pathlib.Path(__file__).resolve().parent

STAGE_TO_LIFECYCLE_STAGE = {"confirm": "confirmed", "clearing": "settled"}
PRICE_TOLERANCE_PCT = 0.01     # matches reconciliation/matching_engine.py, expressed as a percent
QUANTITY_TOLERANCE_PCT = 0.01


def classify_observable(price_diff_pct: float | None, quantity_diff_pct: float | None,
                         side_match: bool | None, match_status: str, lifecycle_status: str | None) -> str:
    if match_status == "missing":
        return "MISSING_RECORD"
    if side_match is False:
        return "REFERENCE_DATA"
    if quantity_diff_pct is not None and quantity_diff_pct > QUANTITY_TOLERANCE_PCT:
        return "QUANTITY"
    if price_diff_pct is not None and price_diff_pct > PRICE_TOLERANCE_PCT:
        return "PRICING"
    if lifecycle_status in ("late", "breached"):
        return "TIMING"
    return "CLEAN"


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def build_predictions() -> list[dict]:
    reconciliation_rows = _read_csv(RECONCILIATION_DIR / "reconciliation_results.csv")
    lifecycle_rows = _read_csv(LIFECYCLE_DIR / "lifecycle_events.csv")
    lifecycle_status_by_key = {(r["trade_id_ref"], r["stage_code"]): r["status"] for r in lifecycle_rows}

    predictions = []
    for row in reconciliation_rows:
        lifecycle_stage = STAGE_TO_LIFECYCLE_STAGE[row["stage"]]
        lifecycle_status = lifecycle_status_by_key.get((row["trade_id_ref"], lifecycle_stage))
        price_diff = float(row["price_diff_pct"]) if row["price_diff_pct"] else None
        qty_diff = float(row["quantity_diff_pct"]) if row["quantity_diff_pct"] else None
        side_match = {"True": True, "False": False, "": None}[row["side_match"]]

        predicted = classify_observable(price_diff, qty_diff, side_match, row["match_status"], lifecycle_status)
        predictions.append(
            {
                "trade_id_ref": row["trade_id_ref"],
                "stage": row["stage"],
                "predicted_category": predicted,
                "true_category": None,  # filled in by evaluate.py against root_cause_labels.csv
            }
        )
    return predictions


def main() -> None:
    predictions = build_predictions()
    with (OUT_DIR / "rule_based_predictions.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["trade_id_ref", "stage", "predicted_category"])
        writer.writeheader()
        writer.writerows({"trade_id_ref": p["trade_id_ref"], "stage": p["stage"], "predicted_category": p["predicted_category"]} for p in predictions)
    print(f"wrote {len(predictions)} rule-based predictions")


if __name__ == "__main__":
    main()
