# aging/ — Multi-Day Rolling Reconciliation with Break Aging

`break_aging.py` takes every non-`CLEAN` break from
`root_cause/root_cause_labels.csv` (2,601 of them) and simulates 15 daily
reconciliation cycles — real calendar dates, run over each break's
disclosed synthetic resolution date. Loaded into `break_aging_daily`
(rolling view) and `break_aging_summary` (aggregate view) via
`sql/ingest_aging.sql`.

## The real-data constraint, disclosed up front

The plan calls for a genuine multi-day rolling cycle over "the real trade
data's actual date range." That range is a single real day. This module doesn't fabricate multi-day trade
data to route around that — it uses **real, un-fabricated calendar
dates** as simulated "as of" checkpoints, running the same fixed set of
real breaks through 15 daily observations. Every date in
`break_aging_daily.csv` is a real calendar date; what's simulated is that
a reconciliation batch job ran on it, not the date itself.

## What's synthetic here (disclosed)

Each break's **resolution date** — no public source publishes real firms'
remediation timelines, the same reason the clearing/confirm discrepancies
themselves are synthetic (`data/synthetic/README.md`). Deterministic,
seeded distribution:

| outcome | rate | actual result |
|---|---:|---:|
| resolved same day | 40% | 1,039 |
| resolved in 1–2 days | 30% | 795 |
| resolved in 3–7 days | 20% | 513 |
| never resolved (14-day window) | 10% | 254 |

## Escalation tiers (disclosed judgment call, real grounding)

Loosely adapted from SEC **Reg SHO Rule 204**'s real day-count escalation
structure for fails-to-deliver — T+1 initial close-out requirement, a
5-consecutive-settlement-day "threshold security" flag, a
13-consecutive-settlement-day mandatory close-out. Real precedent for why
age-based escalation tiers are a genuine pattern in this domain — **not**
a claim that Reg SHO's exact day counts apply to reconciliation-break
aging (a related but distinct concept from fails-to-deliver, which
ReconEngine doesn't model). ReconEngine's tiers:

| tier | age (days) |
|---|---|
| `TIER1_NORMAL` | 0–1 |
| `TIER2_ESCALATED` | 2–5 |
| `TIER3_MANAGEMENT` | 6–13 |
| `TIER4_CRITICAL_AGED` | 14+ |

## Result (live, rolling trend)

Open-break count by day, from `break_aging_daily`:

| date | open breaks | tier |
|---|---:|---|
| 2026-08-19 | 1,562 | TIER1 |
| 2026-08-21 | 767 | TIER2 |
| 2026-08-25 | 359 | TIER3 |
| 2026-08-26 → 09-01 | 254 (flat) | TIER3 |
| 2026-09-02 | 254 | TIER4 |

The 254-break plateau *is* the 10% never-resolved rate — the count stops
declining once every resolvable break has resolved, and the remaining
254 age straight through to `TIER4_CRITICAL_AGED` at day 14. This is
exactly the "aged fails" pattern real reconciliation/settlement
operations teams triage.
