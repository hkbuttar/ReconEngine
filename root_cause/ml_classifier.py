"""Step 7 (ML half): trains an XGBoost multiclass classifier on the same
observable features the rule-based classifier uses (root_cause/rule_based_classifier.py)
-- price_diff_pct, quantity_diff_pct, side_match, match_status,
lifecycle_status -- to predict root_cause_category, then evaluates it on
a held-out test split against root_cause_labels.csv's ground truth.

Same no-leakage discipline as the rule-based classifier: injected_break_type
is never a feature, only the evaluation target.

Honest framing (see root_cause/README.md for the full comparison): this
project's synthetic breaks are deterministic and mutually exclusive by
construction, so the label is a near-exact function of the observable
features -- there's no hidden nonlinear pattern for a gradient-boosted
model to discover that a hand-written rule can't already express. A
near-tie between the two classifiers here is the *expected*, honest
result on this data, not a disappointing one -- it's evidence the labeling
pipeline is internally consistent, not evidence that ML adds nothing over
rules in general. Real trade data, with genuine noise and overlapping
break causes, is where that comparison would actually differentiate.
"""

from __future__ import annotations

import csv
import pathlib

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

RECONCILIATION_DIR = pathlib.Path(__file__).resolve().parent.parent / "reconciliation"
LIFECYCLE_DIR = pathlib.Path(__file__).resolve().parent.parent / "lifecycle"
ROOT_CAUSE_DIR = pathlib.Path(__file__).resolve().parent

STAGE_TO_LIFECYCLE_STAGE = {"confirm": "confirmed", "clearing": "settled"}
RANDOM_SEED = 42


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def build_feature_frame() -> pd.DataFrame:
    reconciliation_rows = _read_csv(RECONCILIATION_DIR / "reconciliation_results.csv")
    lifecycle_rows = _read_csv(LIFECYCLE_DIR / "lifecycle_events.csv")
    labels = {(r["trade_id_ref"], r["stage"]): r["root_cause_category"] for r in _read_csv(ROOT_CAUSE_DIR / "root_cause_labels.csv")}
    lifecycle_status_by_key = {(r["trade_id_ref"], r["stage_code"]): r["status"] for r in lifecycle_rows}

    rows = []
    for row in reconciliation_rows:
        key = (row["trade_id_ref"], row["stage"])
        lifecycle_stage = STAGE_TO_LIFECYCLE_STAGE[row["stage"]]
        lifecycle_status = lifecycle_status_by_key.get((row["trade_id_ref"], lifecycle_stage), "unknown")
        rows.append(
            {
                "trade_id_ref": row["trade_id_ref"],
                "stage": row["stage"],
                "price_diff_pct": float(row["price_diff_pct"]) if row["price_diff_pct"] else 0.0,
                "quantity_diff_pct": float(row["quantity_diff_pct"]) if row["quantity_diff_pct"] else 0.0,
                "side_match": {"True": 1, "False": 0, "": -1}[row["side_match"]],
                "match_status": row["match_status"],
                "lifecycle_status": lifecycle_status,
                "root_cause_category": labels[key],
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    df = build_feature_frame()

    X = pd.get_dummies(df[["price_diff_pct", "quantity_diff_pct", "side_match", "match_status", "lifecycle_status", "stage"]],
                        columns=["match_status", "lifecycle_status", "stage"])
    classes = sorted(df["root_cause_category"].unique())
    class_to_idx = {c: i for i, c in enumerate(classes)}
    y = df["root_cause_category"].map(class_to_idx)

    X_train, X_test, y_train, y_test, idx_train, idx_test = train_test_split(
        X, y, df.index, test_size=0.3, random_state=RANDOM_SEED, stratify=y
    )

    model = XGBClassifier(
        n_estimators=100, max_depth=4, learning_rate=0.1,
        objective="multi:softmax", num_class=len(classes),
        random_state=RANDOM_SEED, eval_metric="mlogloss",
    )
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    accuracy = accuracy_score(y_test, y_pred)
    report = classification_report(y_test, y_pred, target_names=classes, output_dict=True, zero_division=0)
    cm = confusion_matrix(y_test, y_pred, labels=list(range(len(classes))))

    feature_importance = dict(zip(X.columns, model.feature_importances_.round(4).tolist()))

    predictions_df = pd.DataFrame(
        {
            "trade_id_ref": df.loc[idx_test, "trade_id_ref"].values,
            "stage": df.loc[idx_test, "stage"].values,
            "predicted_category": [classes[i] for i in y_pred],
            "true_category": [classes[i] for i in y_test],
        }
    )
    predictions_df.to_csv(ROOT_CAUSE_DIR / "ml_predictions.csv", index=False)

    summary = {
        "n_train": len(X_train),
        "n_test": len(X_test),
        "classes": classes,
        "accuracy": round(float(accuracy), 4),
        "per_class_report": {k: v for k, v in report.items() if k in classes},
        "confusion_matrix": cm.tolist(),
        "feature_importance": dict(sorted(feature_importance.items(), key=lambda kv: -kv[1])),
    }
    import json

    (ROOT_CAUSE_DIR / "ml_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
