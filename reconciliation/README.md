# reconciliation/ — Matching Engine (Step 5)

`matching_engine.py` matches every real trade against the two synthetic
external records at each stage (clearing, confirm), classifying each pair
as `matched`, `broken`, or `missing`. See the module docstring for full
tolerance rationale. Loaded into the live schema via
`sql/ingest_reconciliation.sql` — Step 6/7 (root-cause classification)
and Qlik (Step 15) build on `reconciliation_results` directly, not on the
raw synthetic CSVs.

## Result (live, current trade set)

| stage | matched | broken | missing |
|---|---:|---:|---:|
| clearing | 10,012 | 769 | 227 |
| confirm | 10,078 | 723 | 207 |

## Self-validation against ground truth

Every synthetic row carries its true `injected_break_type`
(`data/synthetic/README.md`), so the engine's own matched/broken calls can
be scored against a known-correct answer, not just eyeballed:

**100% accuracy** on both stages — every `price_mismatch`,
`quantity_mismatch`, and `side_mismatch` row is correctly caught as
`broken`; every clean row is correctly called `matched`; zero false
positives, zero false negatives. `timing_breach` rows are excluded from
this score, not swept under it — see "What this engine does and doesn't
check" below.

**A real bug surfaced by this scoring, fixed at the source**: the first
run showed 50/348 (clearing) `quantity_mismatch` rows scoring as false
negatives. Root cause: `data/synthetic/generate_synthetic_records.py`'s
perturbation rounds to 8 decimal places, and crypto trade sizes can
already sit at that precision's floor (`1e-8`) — a 0.1–2% relative
perturbation of a value that small rounds back to the *exact same*
8-decimal figure, silently no-op'ing the injected break. Fixed in the
generator (forces a minimal-but-real difference when this happens),
Step 2's synthetic data regenerated and reloaded, confirmed
0/348 after the fix. Disclosed here rather than quietly re-run, since
it's a real artifact of representing crypto's precision floor, not
noise.

## What this engine does and doesn't check

Field matching only: price, quantity, side. **Not** timing — a
`timing_breach` row has genuinely unperturbed price/quantity/side (only
its `received_at` timestamp is late), so this engine correctly calls it
`matched`. Timing correctness is a different, already-covered question,
answered by `lifecycle/state_machine.py`'s `on_time`/`late`/`breached`
status (Step 3). Conflating the two would double-count the same
underlying break under two different labels.

## Fuzzy matching (orphan records)

Per the plan's "match on trade ID where available, fuzzy composite key
otherwise": for each `orphan` synthetic record (no real trade behind it
by construction — `data/synthetic/README.md`), the engine searches
still-`missing` real trades for a plausible match — same venue+symbol,
within 1 hour, price/quantity within 5% (a deliberately wide tolerance —
"might be the same trade under a corrupted key," not a match).

**Honest finding, not just a number**: 73/110 clearing orphans and
76/110 confirm orphans turn up *at least one* candidate — but the
candidate-count distribution is wide (many orphans have 5–13 candidates,
only 23/110 have exactly one). At 11,000 trades in a ~7-minute real
market window, a 5%/1-hour tolerance is loose enough to spuriously match
almost anything nearby — this is itself a useful, disclosed lesson about
fuzzy-matching false-positive risk in dense trade data, not evidence that
these orphans are secretly real trades. Reported as candidate lists
(`fuzzy_match_{clearing,confirm}.csv`), not auto-resolved or persisted to
the DB — a human (or a tighter, deliberately-tuned tolerance) would need
to adjudicate an ambiguous multi-candidate match, which this project
doesn't attempt to automate.

## Tolerances (disclosed judgment calls)

`PRICE_TOLERANCE_PCT` / `QUANTITY_TOLERANCE_PCT` = 0.01% relative
difference — two orders of magnitude below the smallest injected
mismatch (0.1%), so it cannot accidentally wave through a real break.
Since clean synthetic rows are bit-exact by construction, this
tolerance's role here is demonstrating the technique and guarding
defensively against float/rounding drift, not rescuing genuinely noisy
real-world data. `side` has no tolerance concept — any mismatch is a
break.
