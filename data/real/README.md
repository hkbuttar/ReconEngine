# data/real/ — what's real here, precisely

Everything under this directory is real, publicly verifiable data. Nothing
in `data/real/` is fabricated or simulated.

## trades_real.csv (+ raw/*.csv)

11,000 real trades pulled live from three venues' public, unauthenticated
market-data APIs by [`ingestion/acquire_real_trades.py`](../../ingestion/acquire_real_trades.py):

| venue    | count | native id source          | API endpoint |
|----------|------:|----------------------------|--------------|
| Binance  | 5,000 | real aggTrade first-trade-id | `data-api.binance.vision/api/v3/aggTrades` |
| Coinbase | 5,000 | real trade_id | `api.exchange.coinbase.com/products/BTC-USD/trades` |
| Kraken   | 1,000 | real trade_id | `api.kraken.com/0/public/Trades` |

Every row is a real execution reported by the venue itself: real trade id,
real price, real quantity, real side, real timestamp. See `manifest.json`
for the exact pull time and endpoint used. `raw/*.csv` preserve each
venue's native field names/values unmodified; `trades_real.csv` is the
common normalized schema (`venue, native_trade_id, symbol, side, price,
quantity, traded_at`) all downstream steps build on.

**What this data is not**: it's public market trade tape (every
participant's executions on that venue), not one firm's private order
fills. ReconEngine treats each row as if it were "this firm's" trade for
reconciliation purposes — a standard portfolio-project stand-in, disclosed
here rather than left implicit. Every row is also necessarily a *taker*
fill from the aggressor's side, since public trade tape never discloses
the resting counterparty (see `fee_schedules.py`'s docstring).

**Volume**: this is a real but modest sample (~7 minutes of live market
activity across three venues at pull time). `performance/` later
replicates and extends this real sample to a high-volume scenario for
load testing — disclosed there as volume-scaling on top of genuinely real
individual trades, not fabricated ones.

## fee_schedules.py

Real, published maker/taker fee rates for Binance, Coinbase, and Kraken,
adapted from `execedge/venues/fees.py` (same project family, verified
2026-08-06) — see that file's docstring, reproduced here, for full
per-venue sourcing and citations. Used in `invoice_recon/` to compute
*expected* fee line items against `trades_real.csv`'s real volume.

## settlement_rules.py

The real US equities T+1 settlement convention (SEC Release No. 34-96930,
effective 2024-05-28) and real crypto near-instant/T+0 settlement
convention, both cited directly. Grounds `lifecycle/`'s state machine
timing expectations — see that module's docstring for the disclosed
judgment call in applying the equities convention to this project's
crypto trade data.

## What's NOT real (lives in data/synthetic/ instead)

`clearing_statements` and `exchange_confirms` — the records a firm's
clearing firm and the exchange's own confirmation feed would produce for
each trade — plus the specific discrepancies between those records and
`trades_real.csv`. No public source publishes internal system-to-system
trade mismatches (that data is exactly what real firms' reconciliation
teams exist to keep private), so this layer is synthetically generated,
*derived from* the real trades above rather than invented independently.
Every synthetic table/column is labeled as such at the point it's
introduced — see `data/synthetic/README.md` once that layer is built.
