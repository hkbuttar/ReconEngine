"""Step 11: exportable trade break / exception report, structured around
a real industry precedent for coded exception reporting rather than an
ad-hoc layout.

Real citation, verified live during this step: SWIFT ISO 15022 message
type MT548 (Settlement Status and Processing Advice) uses a dedicated
Reason Code field (24B) to carry a controlled vocabulary of structured
break/status reasons -- e.g. code NMAS ("No Matching Started"), verified
directly at iotafinance.com/en/SWIFT-ISO15022-View-Code-NMAS.html, which
confirms the field/message pairing (field 24B, MT548 "field 12"). This
project does not claim to emit valid MT548 messages -- MT548 is
specifically a settlement-instruction-status message for a single trade,
not a multi-category exception report -- and does not reuse MT548's exact
4-letter codes, since the rest of that code list wasn't independently
verified here (disclosed rather than guessed at). What's grounded in it
is the *structure*: a coded reason field with a controlled vocabulary is
real, standard industry practice, not this project's invention -- so the
report below uses ReconEngine's own real, cited taxonomy codes
(root_cause/taxonomy.py, Step 6 -- TIMING, PRICING, QUANTITY,
REFERENCE_DATA, MISSING_RECORD) in that same structural role.

Joins root_cause_labels (category), break_aging_summary (age/status), and
invoice_reconciliation (financial impact, where applicable) into one
export -- one row per break.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = pathlib.Path(__file__).resolve().parent


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def main() -> None:
    trades = {f"{t['venue']}:{t['native_trade_id']}": t for t in _read_csv(REPO_ROOT / "data" / "real" / "trades_real.csv")}
    aging = {(r["trade_id_ref"], r["stage"]): r for r in _read_csv(REPO_ROOT / "aging" / "break_aging_summary.csv")}
    invoice_by_ref = {r["trade_id_ref"]: r for r in _read_csv(REPO_ROOT / "invoice_recon" / "invoice_reconciliation.csv")}
    labels = _read_csv(REPO_ROOT / "root_cause" / "root_cause_labels.csv")

    report_rows = []
    for row in labels:
        if row["root_cause_category"] == "CLEAN":
            continue
        key = (row["trade_id_ref"], row["stage"])
        age_row = aging.get(key)
        trade = trades.get(row["trade_id_ref"], {})
        invoice_row = invoice_by_ref.get(row["trade_id_ref"])

        financial_impact = ""
        if invoice_row and invoice_row["match_status"] != "matched" and invoice_row["delta_usd"]:
            financial_impact = invoice_row["delta_usd"]

        report_rows.append(
            {
                "break_reference": f"{row['trade_id_ref']}|{row['stage']}",
                "venue": trade.get("venue", ""),
                "symbol": trade.get("symbol", ""),
                "stage": row["stage"],
                "break_category_code": row["root_cause_category"],
                "has_timing_issue": row["has_timing_issue"],
                "origin_date": age_row["origin_date"] if age_row else "",
                "status": "RESOLVED" if age_row and age_row["resolved_date"] else "OPEN",
                "resolved_date": age_row["resolved_date"] if age_row else "",
                "age_days_or_final": age_row["resolution_days"] if age_row and age_row["resolution_days"] else "",
                "escalation_tier": age_row["max_escalation_tier_reached"] if age_row else "",
                "financial_impact_usd": financial_impact,
            }
        )

    report_rows.sort(key=lambda r: (r["escalation_tier"], r["break_reference"]))

    out_path = OUT_DIR / "exception_report.csv"
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(report_rows[0].keys()))
        writer.writeheader()
        writer.writerows(report_rows)

    header = (
        f"TRADE BREAK / EXCEPTION REPORT\n"
        f"Generated: {dt.datetime.now(tz=dt.timezone.utc).isoformat()}\n"
        f"Reporting entity: ReconEngine (illustrative)\n"
        f"Total open/resolved breaks: {len(report_rows)}\n"
    )
    (OUT_DIR / "exception_report_header.txt").write_text(header)

    from collections import Counter

    summary = {
        "total_breaks_reported": len(report_rows),
        "by_status": dict(Counter(r["status"] for r in report_rows)),
        "by_category": dict(Counter(r["break_category_code"] for r in report_rows)),
        "by_escalation_tier": dict(Counter(r["escalation_tier"] for r in report_rows)),
        "rows_with_financial_impact": sum(1 for r in report_rows if r["financial_impact_usd"]),
    }
    import json

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
