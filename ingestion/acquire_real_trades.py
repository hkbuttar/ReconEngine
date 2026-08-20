"""Pulls real, public trade tape from three venues' public market-data APIs
and normalizes them into ReconEngine's `trades` anchor dataset.

This is the ONLY data-acquisition step in the project that talks to a live
network source. Everything downstream (clearing statements, exchange
confirms, the discrepancies between them) is synthetically generated from
this real data -- see data/real/README.md for the full real-vs-synthetic
disclosure.

Sources (all public, unauthenticated, no API key required):
  - Binance: https://data-api.binance.vision/api/v3/aggTrades
    Binance's own read-only public mirror of api.binance.com (api.binance.com
    itself 451s from this environment's network location; the mirror is the
    documented workaround, not a scrape). Same pattern already used in
    bookmaker/data/binance_capture.py for this project family.
    aggTrades aggregates same-price fills from a single taker order under one
    id, and carries the real first/last individual trade ids (f, l) alongside
    it -- real ids, real prices, real quantities, real timestamps.
  - Coinbase: https://api.exchange.coinbase.com/products/{product}/trades
    Coinbase's public Exchange market-data API. Paginated via the CB-AFTER
    response header (walks backward in time from the most recent trade).
  - Kraken: https://api.kraken.com/0/public/Trades
    Kraken's public market-data API. Paginated via the `since` param (the
    `last` field in each response is the cursor for the next page, walking
    forward in time).

Each venue uses its own native trade id, symbol spelling, and side
convention -- deliberately preserved as-is in data/real/raw/*.csv (raw,
unmodified fields) and only normalized into a common schema in the combined
data/real/trades_real.csv (venue, native_trade_id, symbol, side, price,
quantity, traded_at UTC ISO-8601). The native id is what the lifecycle state
machine and matching engine treat as the real trade's primary key.

Volume note: this pulls a real but modest sample per venue (a few thousand
trades over a recent time window) -- enough to be a genuine real-data anchor,
not enough to be a high-volume dataset on its own. performance/
replicates and extends this real sample to a high-volume scenario, disclosed
there as a volume-scaling technique applied on top of genuinely real
individual trade records, not fabricated trades.

Re-run this script to pull a fresh real sample; each run overwrites the
files under data/real/ and stamps a new `pulled_at` in the manifest.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib
import time
import urllib.error
import urllib.request

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "real"
RAW_DIR = DATA_DIR / "raw"

BINANCE_BASE = "https://data-api.binance.vision"
COINBASE_BASE = "https://api.exchange.coinbase.com"
KRAKEN_BASE = "https://api.kraken.com"

# Real trading pairs covered by execedge's verified fee schedules
# (execedge/venues/fees.py), kept consistent across the project family.
BINANCE_SYMBOL = "BTCUSDT"
COINBASE_PRODUCT = "BTC-USD"
KRAKEN_PAIR = "XBTUSD"

PAGES_PER_VENUE = 5  # ~1000 real trades/page -> a few thousand real trades/venue
REQUEST_DELAY_SECONDS = 0.3  # polite pacing against public, unauthenticated APIs


def _get_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "reconengine-research/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_binance(symbol: str, pages: int) -> list[dict]:
    """Walks backward from the most recent real trade via aggTrades, using
    the real `f` (first individual trade id) of each page as the next
    page's upper bound so pages don't overlap."""
    trades: list[dict] = []
    end_id: int | None = None
    seen_agg_ids: set[int] = set()
    for _ in range(pages):
        if end_id is None:
            url = f"{BINANCE_BASE}/api/v3/aggTrades?symbol={symbol}&limit=1000"
        else:
            url = f"{BINANCE_BASE}/api/v3/aggTrades?symbol={symbol}&fromId={max(end_id - 1000, 0)}&limit=1000"
        batch = _get_json(url)
        if not batch:
            break
        batch = [row for row in batch if row["a"] not in seen_agg_ids]
        if not batch:
            break
        seen_agg_ids.update(row["a"] for row in batch)
        for row in batch:
            trades.append(
                {
                    "venue": "binance",
                    "native_trade_id": row["f"],  # first individual trade id in the aggregate
                    "agg_trade_id": row["a"],
                    "symbol": symbol,
                    "side": "sell" if row["m"] else "buy",  # m=True: buyer is maker -> taker sold
                    "price": row["p"],
                    "quantity": row["q"],
                    "traded_at": dt.datetime.fromtimestamp(row["T"] / 1000, tz=dt.timezone.utc).isoformat(),
                }
            )
        end_id = batch[0]["a"]
        time.sleep(REQUEST_DELAY_SECONDS)
    return trades


def fetch_coinbase(product: str, pages: int) -> list[dict]:
    trades: list[dict] = []
    seen_trade_ids: set[int] = set()
    after_cursor: str | None = None
    for _ in range(pages):
        url = f"{COINBASE_BASE}/products/{product}/trades?limit=1000"
        if after_cursor:
            url += f"&after={after_cursor}"
        req = urllib.request.Request(url, headers={"User-Agent": "reconengine-research/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                after_cursor = resp.headers.get("CB-AFTER")
                batch = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                time.sleep(2.0)
                continue
            raise
        if not batch:
            break
        for row in batch:
            if row["trade_id"] in seen_trade_ids:
                continue
            seen_trade_ids.add(row["trade_id"])
            trades.append(
                {
                    "venue": "coinbase",
                    "native_trade_id": row["trade_id"],
                    "agg_trade_id": "",
                    "symbol": product,
                    "side": row["side"],
                    "price": row["price"],
                    "quantity": row["size"],
                    "traded_at": row["time"],
                }
            )
        if not after_cursor:
            break
        time.sleep(REQUEST_DELAY_SECONDS)
    return trades


def fetch_kraken(pair: str, pages: int) -> list[dict]:
    trades: list[dict] = []
    seen_trade_ids: set[int] = set()
    since: str | None = None
    for _ in range(pages):
        url = f"{KRAKEN_BASE}/0/public/Trades?pair={pair}&count=1000"
        if since:
            url += f"&since={since}"
        payload = _get_json(url)
        if payload.get("error"):
            break
        result = payload["result"]
        pair_key = next(k for k in result if k != "last")
        batch = result[pair_key]
        if not batch:
            break
        new_in_batch = 0
        for row in batch:
            price, volume, ts, side, _order_type, _misc, trade_id = row
            if trade_id in seen_trade_ids:
                continue
            seen_trade_ids.add(trade_id)
            new_in_batch += 1
            trades.append(
                {
                    "venue": "kraken",
                    "native_trade_id": trade_id,
                    "agg_trade_id": "",
                    "symbol": pair,
                    "side": "buy" if side == "b" else "sell",
                    "price": price,
                    "quantity": volume,
                    "traded_at": dt.datetime.fromtimestamp(float(ts), tz=dt.timezone.utc).isoformat(),
                }
            )
        since = result["last"]
        if new_in_batch == 0:
            # Kraken's `since` walks forward in real time; once a page brings
            # no new trades, we've caught up to the live tape and further
            # polling won't surface more real history within this session.
            break
        time.sleep(REQUEST_DELAY_SECONDS)
    return trades


def _write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    pulled_at = dt.datetime.now(tz=dt.timezone.utc).isoformat()

    binance_trades = fetch_binance(BINANCE_SYMBOL, PAGES_PER_VENUE)
    coinbase_trades = fetch_coinbase(COINBASE_PRODUCT, PAGES_PER_VENUE)
    kraken_trades = fetch_kraken(KRAKEN_PAIR, PAGES_PER_VENUE)

    _write_csv(RAW_DIR / "binance_trades_raw.csv", binance_trades)
    _write_csv(RAW_DIR / "coinbase_trades_raw.csv", coinbase_trades)
    _write_csv(RAW_DIR / "kraken_trades_raw.csv", kraken_trades)

    combined_raw = binance_trades + coinbase_trades + kraken_trades
    seen: set[tuple[str, str]] = set()
    combined: list[dict] = []
    for row in combined_raw:
        key = (row["venue"], str(row["native_trade_id"]))
        if key in seen:
            continue
        seen.add(key)
        combined.append(row)
    combined.sort(key=lambda r: r["traded_at"])
    _write_csv(DATA_DIR / "trades_real.csv", combined)

    manifest = {
        "pulled_at": pulled_at,
        "sources": {
            "binance": f"{BINANCE_BASE}/api/v3/aggTrades?symbol={BINANCE_SYMBOL}",
            "coinbase": f"{COINBASE_BASE}/products/{COINBASE_PRODUCT}/trades",
            "kraken": f"{KRAKEN_BASE}/0/public/Trades?pair={KRAKEN_PAIR}",
        },
        "counts": {
            "binance": len(binance_trades),
            "coinbase": len(coinbase_trades),
            "kraken": len(kraken_trades),
            "total": len(combined),
        },
    }
    (DATA_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
