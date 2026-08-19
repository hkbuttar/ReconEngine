"""Real, documented settlement-cycle conventions used to ground the
lifecycle state machine's (lifecycle/) timing expectations between the
"confirmed" and "settled" transitions.

  - US equities: T+1 (trade date plus one business day). SEC amendments to
    Exchange Act Rule 15c6-1 shortened the standard settlement cycle from
    T+2 to T+1, compliance date 2024-05-28. Source: SEC Release No.
    34-96930, "Shortening the Securities Transaction Settlement Cycle"
    (adopted 2023-02-15, effective 2024-05-28).
  - Crypto (the asset class data/real/trades_real.csv is actually drawn
    from): no T+n convention -- ownership and the exchange's internal
    ledger update effectively immediately on execution, since there is no
    separate central clearinghouse/DTCC-style intermediary in the retail
    spot flow captured here. On-chain settlement (moving the asset off-venue
    to a self-custodied wallet) is a separate, user-initiated step with its
    own network confirmation time, not a venue settlement obligation, and is
    out of scope for this project's lifecycle model.

Disclosed judgment call: this project's real trade data (data/real/trades_real.csv)
is crypto spot trades, which don't naturally exercise a T+1 gap. To make the
lifecycle state machine's settlement stage meaningful (and to give the
reconciliation engine a real timing rule to check breaks against, matching
the "trade lifecycle support" framing this project is built for), the
synthetic clearing_statements/exchange_confirms layer (data/synthetic/)
applies the real T+1 equities convention as the expected confirm->settle
timing target for every trade, disclosed here as a deliberate modeling
choice, not a claim that these specific crypto trades actually settle T+1.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SettlementConvention:
    asset_class: str
    settlement_offset_business_days: int
    source: str
    note: str


SETTLEMENT_CONVENTIONS: dict[str, SettlementConvention] = {
    "us_equities": SettlementConvention(
        asset_class="us_equities",
        settlement_offset_business_days=1,
        source="SEC Release No. 34-96930, effective 2024-05-28 (T+1)",
        note="Standard cycle for US equities, corporate/municipal bonds, "
        "and unit investment trusts under amended Exchange Act Rule 15c6-1.",
    ),
    "crypto_spot": SettlementConvention(
        asset_class="crypto_spot",
        settlement_offset_business_days=0,
        source="Venue-internal ledger update on execution; no central "
        "clearinghouse intermediary in retail spot flow.",
        note="Effectively immediate/T+0. Applied here as the real-world "
        "reference point, not as the timing rule this project's lifecycle "
        "state machine tests against -- see module docstring.",
    ),
}

# The convention ReconEngine's synthetic clearing/confirm layer actually
# applies to data/real/trades_real.csv's trades -- see module docstring
# for why crypto data is modeled against the equities T+1 convention.
LIFECYCLE_SETTLEMENT_TARGET = SETTLEMENT_CONVENTIONS["us_equities"]
