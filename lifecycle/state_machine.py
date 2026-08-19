"""Derives lifecycle_events (+ settlements, accounting_feed) rows for
every real trade, by combining data/real/trades_real.csv with Step 2's
synthetic clearing_statements.csv / exchange_confirms.csv.

Stage mapping (the 5 stages are fixed by lifecycle_stage_ref, sql/schema.sql):

  1. captured             <- the real trade itself (traded_at)
  2. sent_to_clearing     <- internal dispatch action: a fixed short lag,
                              not gated on any external record (it's our
                              own front-office action), so always on_time
  3. confirmed            <- exchange_confirms (fast: 5s-15min normal lag
                              per data/synthetic/generate_synthetic_records.py)
  4. settled              <- clearing_statements (slow: 30min-6h normal
                              lag, same source) evaluated against the real
                              T+1 settlement convention
                              (data/real/settlement_rules.py) as the
                              expected_by target
  5. posted_to_accounting <- internal posting action: fixed short lag
                              after settlement

This ordering -- exchange confirmation before clearing settlement -- is
deliberate, not incidental: exchange_confirms' normal lag (5s-15min) is
genuinely faster than clearing_statements' (30min-6h) in the Step 2
generator, matching how real trade confirmation actually outpaces
clearing-cycle settlement. Mapping the faster source to the earlier stage
keeps entered_at timestamps monotonically increasing across the 5 stages
in the normal case.

Gating rule (disclosed judgment call): a trade with a `missing`
clearing_statement or exchange_confirm simply never reaches that stage --
no lifecycle_events row is written for it, or for anything downstream.
This project models settlement and accounting posting as gated on
confirmation, not optimistically continued regardless of upstream breaks.
A trade that never reaches posted_to_accounting is itself a real
monitoring signal (Step 14), not a bug.

Monotonicity guard: `settled`'s entered_at is
max(clearing_statement.received_at, confirmed's entered_at) -- settlement
can't be recorded before the confirmation gating it, even on the rare
occasion a clearing_statement's raw timestamp would otherwise predate a
timing-breached confirm.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from data.real.settlement_rules import LIFECYCLE_SETTLEMENT_TARGET  # noqa: E402

REAL_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "real"
SYNTHETIC_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "synthetic"
OUT_DIR = pathlib.Path(__file__).resolve().parent

# Internal-action lags: fixed, not randomized -- these are our own actions
# with no external record to vary against, so there's nothing to be "late"
# relative to except a target we set ourselves. Disclosed judgment calls.
DISPATCH_LAG = dt.timedelta(seconds=10)
POSTING_LAG = dt.timedelta(hours=2)
POSTING_SLA = dt.timedelta(hours=6)  # same-business-day posting target

# expected_by target for `confirmed`, matching the generator's own
# disclosed "normal" confirm lag upper bound (data/synthetic/README.md).
CONFIRM_SLA = dt.timedelta(minutes=15)

# late vs. breached threshold, applied uniformly across stages: on_time if
# within expected_by; late if overdue by <= 1 day; breached beyond that.
BREACH_THRESHOLD = dt.timedelta(days=1)


def _parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _status(entered_at: dt.datetime, expected_by: dt.datetime) -> str:
    if entered_at <= expected_by:
        return "on_time"
    return "breached" if entered_at - expected_by > BREACH_THRESHOLD else "late"


def _add_business_days(start: dt.datetime, n: int) -> dt.datetime:
    current = start
    added = 0
    while added < n:
        current += dt.timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri
            added += 1
    return current


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def _index_by_trade_ref(rows: list[dict]) -> dict[str, dict]:
    """Keeps only the first (clean-preferring) row per trade_id_ref -- a
    trade could theoretically appear once per stage's CSV, never more."""
    index: dict[str, dict] = {}
    for row in rows:
        ref = row["trade_id_ref"]
        if ref and ref not in index:
            index[ref] = row
    return index


def build_lifecycle(trades: list[dict], clearing_by_ref: dict, confirm_by_ref: dict):
    lifecycle_rows: list[dict] = []
    settlement_rows: list[dict] = []
    accounting_rows: list[dict] = []

    for trade in trades:
        ref = f"{trade['venue']}:{trade['native_trade_id']}"
        traded_at = _parse_ts(trade["traded_at"])

        # Stage 1: captured -- always happens, real trade exists.
        lifecycle_rows.append(
            {"trade_id_ref": ref, "stage_code": "captured", "entered_at": traded_at.isoformat(),
             "expected_by": "", "status": "on_time"}
        )

        # Stage 2: sent_to_clearing -- internal dispatch, always on_time.
        dispatch_at = traded_at + DISPATCH_LAG
        lifecycle_rows.append(
            {"trade_id_ref": ref, "stage_code": "sent_to_clearing", "entered_at": dispatch_at.isoformat(),
             "expected_by": dispatch_at.isoformat(), "status": "on_time"}
        )

        confirm = confirm_by_ref.get(ref)
        if confirm is None:
            continue  # gated: no confirmed/settled/posted_to_accounting without a confirm record

        # Stage 3: confirmed <- exchange_confirms.
        confirmed_at = _parse_ts(confirm["received_at"])
        confirm_expected_by = dispatch_at + CONFIRM_SLA
        lifecycle_rows.append(
            {"trade_id_ref": ref, "stage_code": "confirmed", "entered_at": confirmed_at.isoformat(),
             "expected_by": confirm_expected_by.isoformat(), "status": _status(confirmed_at, confirm_expected_by)}
        )

        clearing = clearing_by_ref.get(ref)
        if clearing is None:
            continue  # gated: no settled/posted_to_accounting without a clearing record

        # Stage 4: settled <- clearing_statements, evaluated against the
        # real T+1 convention. Monotonicity guard vs. `confirmed`.
        clearing_received_at = _parse_ts(clearing["received_at"])
        settled_at = max(clearing_received_at, confirmed_at)
        settle_expected_by = _add_business_days(
            confirmed_at, LIFECYCLE_SETTLEMENT_TARGET.settlement_offset_business_days
        )
        settle_status = _status(settled_at, settle_expected_by)
        lifecycle_rows.append(
            {"trade_id_ref": ref, "stage_code": "settled", "entered_at": settled_at.isoformat(),
             "expected_by": settle_expected_by.isoformat(), "status": settle_status}
        )

        notional = round(float(trade["price"]) * float(trade["quantity"]), 2)
        settlement_rows.append(
            {
                "trade_id_ref": ref,
                "expected_settle_date": settle_expected_by.date().isoformat(),
                "actual_settle_date": settled_at.date().isoformat(),
                "settlement_status": "settled",
                "settlement_amount": f"{notional:.2f}",
                "currency": "USD",
            }
        )

        # Stage 5: posted_to_accounting -- internal posting action.
        posted_at = settled_at + POSTING_LAG
        posting_expected_by = settled_at + POSTING_SLA
        lifecycle_rows.append(
            {"trade_id_ref": ref, "stage_code": "posted_to_accounting", "entered_at": posted_at.isoformat(),
             "expected_by": posting_expected_by.isoformat(),
             "status": _status(posted_at, posting_expected_by)}
        )
        accounting_rows.append(
            {
                "trade_id_ref": ref,
                "gl_account": f"{trade['venue']}:{trade['symbol']}",
                "debit_credit": "D" if trade["side"] == "buy" else "C",
                "amount": f"{notional:.2f}",
                "currency": "USD",
                "posted_at": posted_at.isoformat(),
                "posting_status": "posted",
            }
        )

    return lifecycle_rows, settlement_rows, accounting_rows


def _write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    trades = _read_csv(REAL_DIR / "trades_real.csv")
    clearing_by_ref = _index_by_trade_ref(_read_csv(SYNTHETIC_DIR / "clearing_statements.csv"))
    confirm_by_ref = _index_by_trade_ref(_read_csv(SYNTHETIC_DIR / "exchange_confirms.csv"))

    lifecycle_rows, settlement_rows, accounting_rows = build_lifecycle(trades, clearing_by_ref, confirm_by_ref)

    _write_csv(OUT_DIR / "lifecycle_events.csv", lifecycle_rows)
    _write_csv(OUT_DIR / "settlements.csv", settlement_rows)
    _write_csv(OUT_DIR / "accounting_feed.csv", accounting_rows)

    from collections import Counter

    stage_counts = Counter(r["stage_code"] for r in lifecycle_rows)
    status_by_stage = {
        stage: dict(Counter(r["status"] for r in lifecycle_rows if r["stage_code"] == stage))
        for stage in ["captured", "sent_to_clearing", "confirmed", "settled", "posted_to_accounting"]
    }
    summary = {
        "total_trades": len(trades),
        "stage_reached_counts": dict(stage_counts),
        "status_by_stage": status_by_stage,
        "settlements": len(settlement_rows),
        "accounting_entries": len(accounting_rows),
    }
    import json

    (OUT_DIR / "generation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
