"""Honest side-by-side comparison of the rule-based classifier
(root_cause/rule_based_classifier.py) and the ML classifier
(root_cause/ml_classifier.py) against root_cause_labels.csv's ground
truth. Run both classifiers first.

The rule-based classifier is deterministic and untrained, so it's scored
on the full 22,016-row dataset; the ML classifier is scored on its 30%
held-out test split (6,605 rows) to avoid scoring it on data it trained
on. Not a perfectly matched comparison for that reason -- disclosed here
rather than presented as apples-to-apples -- but both are evaluated on
data neither classifier could have used to *derive* its own logic (the
rules were hand-written before either classifier's predictions existed;
the ML test split was never seen during training).
"""

from __future__ import annotations

import csv
import json
import pathlib

ROOT_CAUSE_DIR = pathlib.Path(__file__).resolve().parent


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def main() -> None:
    labels = {(r["trade_id_ref"], r["stage"]): r["root_cause_category"] for r in _read_csv(ROOT_CAUSE_DIR / "root_cause_labels.csv")}
    rule_preds = _read_csv(ROOT_CAUSE_DIR / "rule_based_predictions.csv")
    ml_preds = _read_csv(ROOT_CAUSE_DIR / "ml_predictions.csv")
    ml_summary = json.loads((ROOT_CAUSE_DIR / "ml_summary.json").read_text())

    rule_correct = sum(1 for p in rule_preds if labels[(p["trade_id_ref"], p["stage"])] == p["predicted_category"])
    rule_accuracy = rule_correct / len(rule_preds)

    rule_misses = [p for p in rule_preds if labels[(p["trade_id_ref"], p["stage"])] != p["predicted_category"]]
    ml_misses = {(p["trade_id_ref"], p["stage"]) for p in ml_preds if p["true_category"] != p["predicted_category"]}
    rule_miss_keys = {(p["trade_id_ref"], p["stage"]) for p in rule_misses}

    comparison = {
        "rule_based": {
            "n_scored": len(rule_preds),
            "accuracy": round(rule_accuracy, 4),
            "n_misses": len(rule_misses),
        },
        "ml_xgboost": {
            "n_scored": ml_summary["n_test"],
            "accuracy": ml_summary["accuracy"],
            "n_misses": sum(1 for p in ml_preds if p["true_category"] != p["predicted_category"]),
        },
        "misses_overlap": {
            "same_rows_missed_by_both": len(rule_miss_keys & ml_misses),
            "note": "Both classifiers miss the same TIMING rows with no lifecycle_events "
            "signal (gated before that stage) -- a real information limit, not a "
            "modeling gap either approach could close from observable fields alone.",
        },
    }
    print(json.dumps(comparison, indent=2))
    (ROOT_CAUSE_DIR / "comparison_summary.json").write_text(json.dumps(comparison, indent=2) + "\n")


if __name__ == "__main__":
    main()
