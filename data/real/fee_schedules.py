"""Real, published maker/taker fee schedules for the three venues covered by
data/real/trades_real.csv, base (lowest, unauthenticated-retail) tier.

Adapted directly from execedge/venues/fees.py (same project family, verified
2026-08-06) rather than re-fetched here, since that module already did the
sourcing work and cross-verification for exactly these three venues. See
that file's docstring for the full per-venue sourcing notes reproduced
below. Re-verify before trusting these for anything beyond this project's
own illustrative reconciliation examples -- fee schedules change (Binance.US's
own did, in April 2026, per the source below).

  - Binance.US: 0% maker, 0.02% taker, flat across all users/pairs, no
    volume tiers. Primary source, fetched directly:
    https://blog.binance.us/zero-fee-trading/
  - Kraken: Tier 1 ($0+ 30-day volume) = 0.40% maker, 0.80% taker.
    Primary source, fetched directly (full 17-tier table retrieved and
    cross-checked for monotonicity): https://www.kraken.com/features/fee-schedule
  - Coinbase Advanced Trade: $0-$10K 30-day volume tier = 0.40% maker,
    0.60% taker. Coinbase's own fee pages returned HTTP 403 to direct fetch
    (bot-blocked) -- these numbers are cross-verified across two independent
    secondary sources that agreed exactly (datawallet.com/crypto/coinbase-fees
    and a second aggregator), not fetched from Coinbase directly. The one
    schedule here with slightly weaker sourcing than the other two.

Disclosed simplification: these are each venue's *base* retail tier. Real
trading desks with meaningful 30-day volume land in far lower fee tiers on
all three venues (e.g. Kraken's fees fall from 0.80% taker at Tier 1 to
0.10% at $250M+ volume) -- reconengine's invoice_recon/ step computes
*expected* fees at this base tier against data/real/trades_real.csv's real
volume, since there is no real trading history here to justify assuming a
higher tier.

Maker/taker in this project's data specifically: data/real/trades_real.csv
is public market trade tape, not a firm's own order fills -- each row is
one execution as reported by the venue, with the side reported being the
*aggressor's* side (the order that crossed the spread and caused the
trade). Public trade tape never discloses the resting counterparty, so
every real trade here is treated as a taker fill for expected-fee
computation in invoice_recon/, the same simplification execedge's fill
model makes explicitly (see its docstring above) for the same reason.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeSchedule:
    venue: str
    maker_fee_bps: float
    taker_fee_bps: float
    source: str


VENUE_FEE_SCHEDULES: dict[str, FeeSchedule] = {
    "binance": FeeSchedule(
        venue="binance", maker_fee_bps=0.0, taker_fee_bps=2.0,
        source="https://blog.binance.us/zero-fee-trading/ (primary, fetched directly)",
    ),
    "coinbase": FeeSchedule(
        venue="coinbase", maker_fee_bps=40.0, taker_fee_bps=60.0,
        source="cross-verified via two independent secondary sources; "
        "coinbase.com/advanced-fees and help.coinbase.com both returned HTTP 403 "
        "to direct fetch in this environment",
    ),
    "kraken": FeeSchedule(
        venue="kraken", maker_fee_bps=40.0, taker_fee_bps=80.0,
        source="https://www.kraken.com/features/fee-schedule (primary, fetched directly, Tier 1)",
    ),
}
