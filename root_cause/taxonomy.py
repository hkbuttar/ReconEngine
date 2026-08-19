"""Step 6: an industry-grounded post-trade break taxonomy, and a
deterministic crosswalk from this project's internal break vocabulary
(data/synthetic/generate_synthetic_records.py's `injected_break_type`,
plus lifecycle timing status) into it.

Real citations, verified directly against fixtrading.org's own FIX
dictionary (fiximate.fixtrading.org) during this step -- not recalled from
memory and left unchecked:
  - FIX Protocol OrdRejReason (tag 103), FIX.4.4: order-level rejection
    reason codes. Several map directly onto post-trade break categories --
    e.g. code 13 "Incorrect quantity", code 1 "Unknown symbol".
  - FIX Protocol ExecRestatementReason (tag 378), FIX.4.4: code 0 is
    literally "GT Corporate action" -- the real, citable grounding for
    this taxonomy's CORPORATE_ACTION category.
  - The real US equities T+1 settlement convention (SEC Release No.
    34-96930, already cited in data/real/settlement_rules.py) grounds
    TIMING.

Disclosed limitation: a DTCC ITP/CTM (Central Trade Matching) citation for
the QUANTITY/PRICING/REFERENCE_DATA categories was attempted during this
step (CTM is the real, industry-standard central matching utility for
exactly this kind of trade-economics matching) but the fetchable DTCC
pages returned either a 404 or an unparseable PDF -- CTM's real-world
purpose is accurately described here from established general knowledge
of the product, not from a directly verified document, and is flagged as
weaker-sourced than the FIX citations above.

This module only defines the taxonomy and crosswalks *known* synthetic
break types onto it -- it does not predict a category from observable
fields alone. That's Step 7's job (rule-based vs. ML classification),
which needs this module's output as labeled ground truth to score against,
the same way Step 5 scored the matching engine against
`injected_break_type` directly.
"""

from __future__ import annotations

import csv
import pathlib
from dataclasses import dataclass

RECONCILIATION_DIR = pathlib.Path(__file__).resolve().parent.parent / "reconciliation"
LIFECYCLE_DIR = pathlib.Path(__file__).resolve().parent.parent / "lifecycle"
OUT_DIR = pathlib.Path(__file__).resolve().parent

# reconciliation stage name -> lifecycle stage_code, per lifecycle/state_machine.py's
# mapping (exchange_confirms -> confirmed, clearing_statements -> settled).
STAGE_TO_LIFECYCLE_STAGE = {"confirm": "confirmed", "clearing": "settled"}


@dataclass(frozen=True)
class Category:
    code: str
    name: str
    description: str
    real_citation: str


TAXONOMY: dict[str, Category] = {
    "CLEAN": Category(
        "CLEAN", "No break",
        "Record matches within tolerance at this stage; not a root-cause category, "
        "included for completeness of the label set.",
        "n/a",
    ),
    "TIMING": Category(
        "TIMING", "Timing / late processing",
        "The record arrived (or was confirmed/settled) later than the expected "
        "processing window, independent of whether its economic fields match.",
        "SEC Release No. 34-96930 (T+1 settlement cycle, effective 2024-05-28) "
        "grounds the expected-by target this is measured against "
        "(data/real/settlement_rules.py); FIX OrdRejReason codes 4 'Too late to "
        "enter' and 8 'Stale Order' are the analogous order-level concept "
        "(verified at fiximate.fixtrading.org/legacy/en/FIX.4.4/tag103.html).",
    ),
    "PRICING": Category(
        "PRICING", "Price discrepancy",
        "Reported price differs from the real trade's execution price beyond "
        "tolerance.",
        "Price is one of the core economic fields DTCC's CTM (Central Trade "
        "Matching) matches between counterparties as standard industry practice "
        "for institutional trade confirmation -- described here from established "
        "product knowledge; a specific DTCC field-list document could not be "
        "directly verified in this pass (see module docstring).",
    ),
    "QUANTITY": Category(
        "QUANTITY", "Quantity discrepancy",
        "Reported quantity differs from the real trade's executed quantity "
        "beyond tolerance.",
        "FIX OrdRejReason code 13 'Incorrect quantity' (and code 14 'Incorrect "
        "allocated quantity') -- verified at "
        "fiximate.fixtrading.org/legacy/en/FIX.4.4/tag103.html.",
    ),
    "REFERENCE_DATA": Category(
        "REFERENCE_DATA", "Reference / static data mismatch",
        "A categorical field (side, symbol, account) disagrees between the real "
        "trade and the reported record -- not a magnitude difference.",
        "FIX OrdRejReason code 1 'Unknown symbol', code 10 'Invalid Investor ID', "
        "code 15 'Unknown account(s)' -- verified at "
        "fiximate.fixtrading.org/legacy/en/FIX.4.4/tag103.html.",
    ),
    "MISSING_RECORD": Category(
        "MISSING_RECORD", "Missing record",
        "The real trade has no corresponding clearing/confirm record at this "
        "stage at all.",
        "Analogous to FIX OrdRejReason code 5 'Unknown Order' -- the "
        "counterparty has no record of the referenced trade -- verified at "
        "fiximate.fixtrading.org/legacy/en/FIX.4.4/tag103.html.",
    ),
    "ORPHAN_RECORD": Category(
        "ORPHAN_RECORD", "Orphan / unexplained record",
        "A clearing/confirm record exists with no corresponding real trade -- "
        "the reverse of MISSING_RECORD.",
        "Analogous to FIX OrdRejReason code 6 'Duplicate Order (e.g. dupe "
        "ClOrdID)' / code 7 'Duplicate of a verbally communicated order' -- an "
        "unexplained record with no legitimate originating order -- verified at "
        "fiximate.fixtrading.org/legacy/en/FIX.4.4/tag103.html.",
    ),
    "CORPORATE_ACTION": Category(
        "CORPORATE_ACTION", "Corporate-action-related break",
        "A break caused by a corporate action (split, dividend, symbol change) "
        "changing the expected trade economics between capture and settlement.",
        "FIX ExecRestatementReason (tag 378) code 0 is literally 'GT Corporate "
        "action' -- verified at "
        "fiximate.fixtrading.org/legacy/en/FIX.4.4/tag378.html. Not exercised by "
        "this project's data: the real trades (data/real/trades_real.csv) are "
        "crypto spot trades, which don't have equities-style corporate actions. "
        "Included for taxonomy completeness and industry grounding, not because "
        "any trade here triggers it -- disclosed rather than silently omitted.",
    ),
}


def crosswalk(match_status: str, injected_break_type: str, lifecycle_status: str | None) -> tuple[str, bool]:
    """Returns (primary_category_code, has_timing_issue). Priority when
    multiple signals are present: MISSING_RECORD > REFERENCE_DATA >
    QUANTITY > PRICING > TIMING > CLEAN -- a trade can be broken on a
    field AND late; the field break is reported as primary with
    has_timing_issue=True rather than picking one arbitrarily."""
    has_timing_issue = lifecycle_status in ("late", "breached")

    if match_status == "missing":
        return "MISSING_RECORD", has_timing_issue
    if injected_break_type == "side_mismatch":
        return "REFERENCE_DATA", has_timing_issue
    if injected_break_type == "quantity_mismatch":
        return "QUANTITY", has_timing_issue
    if injected_break_type == "price_mismatch":
        return "PRICING", has_timing_issue
    if injected_break_type == "timing_breach" or has_timing_issue:
        return "TIMING", has_timing_issue
    return "CLEAN", has_timing_issue


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def main() -> None:
    reconciliation_rows = _read_csv(RECONCILIATION_DIR / "reconciliation_results.csv")
    lifecycle_rows = _read_csv(LIFECYCLE_DIR / "lifecycle_events.csv")

    lifecycle_status_by_key: dict[tuple[str, str], str] = {
        (row["trade_id_ref"], row["stage_code"]): row["status"] for row in lifecycle_rows
    }

    labeled_rows = []
    for row in reconciliation_rows:
        lifecycle_stage = STAGE_TO_LIFECYCLE_STAGE[row["stage"]]
        lifecycle_status = lifecycle_status_by_key.get((row["trade_id_ref"], lifecycle_stage))
        category, has_timing_issue = crosswalk(row["match_status"], row["injected_break_type"], lifecycle_status)
        labeled_rows.append(
            {
                "trade_id_ref": row["trade_id_ref"],
                "stage": row["stage"],
                "root_cause_category": category,
                "has_timing_issue": has_timing_issue,
                "match_status": row["match_status"],
                "injected_break_type": row["injected_break_type"],
                "lifecycle_status": lifecycle_status or "",
            }
        )

    with (OUT_DIR / "root_cause_labels.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(labeled_rows[0].keys()))
        writer.writeheader()
        writer.writerows(labeled_rows)

    from collections import Counter

    by_stage_category = Counter((r["stage"], r["root_cause_category"]) for r in labeled_rows)
    summary = {
        "total_labeled": len(labeled_rows),
        "by_stage_category": {f"{stage}/{cat}": n for (stage, cat), n in sorted(by_stage_category.items())},
        "timing_issue_count": sum(1 for r in labeled_rows if r["has_timing_issue"]),
    }
    import json

    (OUT_DIR / "generation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
