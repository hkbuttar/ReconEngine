# data/synthetic/ — what's synthetic here, precisely

Everything under this directory is synthetically generated. No public
source publishes internal clearing-firm or exchange-confirmation records,
or the discrepancies between those records and a firm's own trade blotter
— that data is exactly what real reconciliation teams exist to keep
private — so this layer is generated rather than sourced.

It is not invented independently, though: every row is *derived from* a
real trade in [`data/real/trades_real.csv`](../real/trades_real.csv) by
[`generate_synthetic_records.py`](generate_synthetic_records.py), and
every row honestly labels whether and how it was perturbed via the
`injected_break_type` column — nothing is silently wrong.

## Files

- `clearing_statements.csv` — one synthetic record per real trade (minus
  injected `missing` breaks, plus injected `orphan` breaks), modeling what
  a clearing firm's statement would report.
- `exchange_confirms.csv` — same idea, modeling the exchange's own
  confirmation feed.
- `generation_summary.json` — exact row counts by break type from the
  last run (regenerate via `python3 data/synthetic/generate_synthetic_records.py`).

Both reference the real trade via `trade_id_ref` = `"{venue}:{native_trade_id}"`
(matching `trades_real.csv`'s natural key), not a SQL `trade_id` — that
surrogate key only exists once a row is loaded into the `trades` table
(Step 4 ETL resolves the reference at load time). `orphan` rows have an
empty `trade_id_ref`: by definition, no real trade backs them.

## Injection methodology (disclosed judgment calls)

Deterministic, seeded (`random.Random(42)`) so reruns against the same
real trades reproduce the same injected breaks. Applied independently to
each stage (clearing vs. confirm) — a given trade can be clean at one
stage and broken at the other.

| break type | rate (of real trades) | what happens |
|---|---:|---|
| `none` (clean match) | 88% | reported fields match the real trade exactly; timestamp offset by a normal processing lag only |
| `missing` | 2% | no synthetic record generated for that stage at all |
| `price_mismatch` | 3% | reported price perturbed ±0.1%–2% |
| `quantity_mismatch` | 3% | reported quantity perturbed ±0.1%–2% |
| `timing_breach` | 3% | received/confirmed 1–3 days late instead of the normal lag |
| `side_mismatch` | 1% | reported side flipped (buy↔sell) |
| `orphan` | +1% (additive, on top of the above) | a synthetic record with **no** matching real trade — the clearing firm/exchange reports something the front office never captured; price/qty synthesized in a real sample trade's neighborhood since there's no real trade to derive it from |

**Normal processing lag** (applied to the 88% clean rows, not just the
broken ones) is an illustrative modeling choice, not a cited industry SLA:
clearing statements land 30 minutes–6 hours after the trade; exchange
confirms land 5 seconds–15 minutes after. A `timing_breach` pushes that to
1–3 days instead. These specific windows are a disclosed judgment call —
see [`data/real/settlement_rules.py`](../real/settlement_rules.py) for the
one settlement timing figure in the project that *is* a real, cited
convention (US equities T+1).

**Why these rates**: chosen to give the downstream reconciliation engine
(Step 5) and root-cause classifiers (Step 7) meaningfully many examples of
every break category, without making "broken" the common case — real
reconciliation is mostly clean matches with a minority of exceptions, and
a dataset that inverted that ratio would misrepresent how the problem
actually looks in practice.

**Ground truth for Step 7**: because every row is labeled with the break
that was (or wasn't) injected, this file doubles as a labeled evaluation
set for comparing the rule-based and ML root-cause classifiers' accuracy
against a known-correct answer — not just against each other.
