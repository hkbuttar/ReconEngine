# lifecycle/ — Trade Lifecycle State Machine (Step 3)

`state_machine.py` derives the 5-stage lifecycle
(`captured → sent_to_clearing → confirmed → settled → posted_to_accounting`,
fixed by `lifecycle_stage_ref` in `sql/schema.sql`) for every real trade,
by combining `data/real/trades_real.csv` with Step 2's synthetic
`clearing_statements.csv` / `exchange_confirms.csv`. See the module
docstring for the full stage-mapping rationale, gating rule, and
monotonicity guard — summarized below.

## Outputs

- `lifecycle_events.csv` — one row per (trade, stage reached): `entered_at`,
  `expected_by`, `status` (`on_time`/`late`/`breached`).
- `settlements.csv`, `accounting_feed.csv` — populated only for trades
  that make it all the way through (see gating rule).
- `generation_summary.json` — counts from the last run.

Loaded into the live SQL Server schema via `sql/load_lifecycle.sql`
(same staging-table + `BULK INSERT` pattern as `sql/load_data.sql`).

## Result (current real trade set, 11,008 trades)

| stage | reached | on_time | late | breached |
|---|---:|---:|---:|---:|
| captured | 11,008 | 11,008 | – | – |
| sent_to_clearing | 11,008 | 11,008 | – | – |
| confirmed | 10,801 | 10,470 | 2 | 329 |
| settled | 10,577 | 10,254 | 152 | 171 |
| posted_to_accounting | 10,577 | 10,577 | – | – |

**431 real trades (11,008 − 10,577) never reach `posted_to_accounting`** —
each stalls at whichever stage's synthetic record was injected as
`missing` (Step 2). That gap is itself the signal a real operations team
would triage; it isn't cleaned up or backfilled here, by design.

## Disclosed judgment calls (see module docstring for full detail)

- **Stage-to-source mapping is deliberate, not arbitrary.**
  `exchange_confirms` (fast, 5s–15min normal lag) maps to `confirmed`
  (stage 3); `clearing_statements` (slow, 30min–6h normal lag) maps to
  `settled` (stage 4) — matching which stage happens sooner in real
  operations, and keeping `entered_at` monotonically increasing across
  stages in the normal case.
- **Gating, not optimistic continuation.** A `missing` clearing or
  confirm record stops the lifecycle there — settlement and accounting
  posting are modeled as requiring confirmation, not assumed to happen
  regardless.
- **`sent_to_clearing` and `posted_to_accounting` are internal actions**
  (fixed 10s / 2h lags, always `on_time`) — there's no external record to
  be late against for either; only `confirmed` and `settled` can be
  `late`/`breached`, since only those are gated on the synthetic records
  that actually carry injected timing breaches.
- **`settled`'s `expected_by`** uses the real, cited T+1 convention
  (`data/real/settlement_rules.py`), business-day aware. It's the one
  timing target in this module backed by a real source rather than an
  illustrative modeling choice.
- **Settlement currency is USD for all three venues**, including
  Binance's USDT-quoted pair — a disclosed 1:1 USDT/USD simplification,
  standard for this kind of illustrative accounting math but not strictly
  accurate (USDT can and does depeg).
