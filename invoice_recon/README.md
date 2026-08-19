# invoice_recon/ — Invoice Reconciliation (Step 9)

`generate_invoice.py` computes **expected** fee line items from real
trade notional (`data/real/trades_real.csv`) against real, published
maker/taker fee schedules (`data/real/fee_schedules.py`), then generates
a synthetically perturbed "actual received invoice" per trade with
disclosed, labeled discrepancies. Loaded into `invoice_reconciliation`
via `sql/ingest_invoice.sql`.

## Real vs. synthetic boundary

- **Real**: the fee rates themselves (Binance 2.0bps, Coinbase 60.0bps,
  Kraken 80.0bps taker — all cited, `data/real/fee_schedules.py`) and the
  trade notional they're applied to.
- **Synthetic (disclosed)**: the "actual invoice" side. No public source
  publishes a firm's real invoice-vs-expected mismatches — same reasoning
  as `data/synthetic/README.md`'s clearing/confirm layer.

**Every trade is billed as a taker fill** — `data/real/fee_schedules.py`'s
disclosed simplification (public trade tape only shows the aggressor
side). **Currency is USD throughout**, including Binance's USDT-quoted
pair — matching `lifecycle/state_machine.py`'s already-disclosed 1:1
USDT/USD simplification.

**Disclosed omission**: the plan's example discrepancy list includes
"missing rebates." This project's fill model has no maker fills (every
trade is a taker), and Binance's own maker fee is 0% — there's no real
rebate structure here to mis-omit, so this category is left out rather
than fabricated to fit the list. `double_billed`, `rate_misapplied`,
`missing_line`, and `rounding_error` are implemented instead.

## Result (live, current trade set)

| venue | matched | discrepant | missing | net delta (USD) |
|---|---:|---:|---:|---:|
| binance | 4,632 | 269 | 99 | +16.02 |
| coinbase | 4,636 | 251 | 113 | +499.93 |
| kraken | 945 | 44 | 19 | +1,377.64 |

## A real bug, found and fixed by the materiality check itself

The first version used a single fixed-dollar materiality threshold
(`$0.01`). Result: **509 genuinely injected discrepancies — 103
`double_billed` (2× the fee) and 83 `rate_misapplied` (≥30% off the real
rate) — were silently called `matched`.** Root cause: on this dataset's
tiny-notional crypto trades, even a *doubled* fee can still be a
fraction of a cent in absolute terms, so an absolute-only threshold
missed large *relative* billing errors entirely.

Fixed by combining absolute and relative materiality — flagged as
material if it fails **either** test, not just the dollar one
(`MATERIALITY_THRESHOLD_USD = $0.01` **and** `MATERIALITY_THRESHOLD_PCT = 10%`,
both must hold for "matched"). Re-verified directly, not just re-run:
**100% of `double_billed` and `rate_misapplied` rows are now caught, zero
clean rows are falsely flagged**, and 144/323 `rounding_error` rows are
now *correctly* flagged material too — on a trade small enough that even
a sub-cent rounding jitter is >10% of the expected fee, "just rounding"
genuinely isn't immaterial anymore. This mirrors the real operational
lesson every fixed-dollar materiality policy eventually runs into on a
book with a wide notional range.

## Also found and fixed: the same scientific-notation bug as Step 2

`round(x, 8)` on a sub-cent fee amount produces Python floats like
`1e-08`, which `str()`/`csv.writer` render as `"1e-08"` — a value SQL
Server's `CAST(... AS DECIMAL)` rejects outright (`Msg 8114`), caught
immediately on the first live load attempt. Same root cause and same fix
as `data/synthetic/generate_synthetic_records.py`'s `_perturb_quantity`
bug (Step 5's README): format every numeric field as a fixed-point string
(`f"{value:.8f}"`) at the point it's written, never rely on Python's
default float-to-string conversion.
