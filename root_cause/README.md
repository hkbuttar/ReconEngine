# root_cause/ — Industry-Grounded Root-Cause Taxonomy (Step 6)

`taxonomy.py` defines 8 break categories and a deterministic crosswalk
from this project's internal break vocabulary (Step 2's
`injected_break_type`, Step 3's lifecycle timing status) onto them.
Loaded into `root_cause_labels` via `sql/ingest_root_cause.sql`. This is
Step 7's ground truth: the rule-based and ML classifiers it builds will
predict these labels *from observable fields alone*, then get scored
against them — the same way Step 5 scored the matching engine.

## Taxonomy

| category | meaning | real citation |
|---|---|---|
| `TIMING` | Late processing/confirmation | SEC Release No. 34-96930 (T+1); FIX `OrdRejReason` codes 4/8 |
| `PRICING` | Price discrepancy | DTCC CTM's standard economic-field matching (see sourcing note below) |
| `QUANTITY` | Quantity discrepancy | FIX `OrdRejReason` code 13 "Incorrect quantity" |
| `REFERENCE_DATA` | Categorical field mismatch (side, symbol, account) | FIX `OrdRejReason` codes 1/10/15 |
| `MISSING_RECORD` | No record at all for a real trade | Analogous to FIX `OrdRejReason` code 5 "Unknown Order" |
| `ORPHAN_RECORD` | Record with no real trade behind it | Analogous to FIX `OrdRejReason` codes 6/7 (duplicate/unexplained) |
| `CORPORATE_ACTION` | Break caused by a corporate action | FIX `ExecRestatementReason` code 0, literally "GT Corporate action" |
| `CLEAN` | No break | n/a — included for label-set completeness |

Full descriptions and citation URLs are in `taxonomy.py`'s `TAXONOMY` dict.

**Sourcing discipline**: every FIX citation above was fetched and
verified directly from `fiximate.fixtrading.org` during this step, not
recalled from memory unchecked — an earlier attempt to cite "FIX tag 378
= OrdRejReason" from recall was wrong (378 is `ExecRestatementReason`;
`OrdRejReason` is tag 103) and caught by actually checking. `PRICING`'s
DTCC CTM citation is the one exception, disclosed as such: CTM's role as
the industry-standard central trade-matching utility is accurately
described from established general knowledge, but the specific DTCC
document that would confirm its exact matched-field list either 404'd or
returned an unparseable PDF when fetched live — flagged as weaker-sourced
than the FIX citations, not silently presented as equally verified.

## Result (live, current trade set)

| stage | CLEAN | TIMING | PRICING | QUANTITY | REFERENCE_DATA | MISSING_RECORD |
|---|---:|---:|---:|---:|---:|---:|
| clearing | 9,668 | 344 | 313 | 348 | 108 | 227 |
| confirm | 9,747 | 331 | 330 | 300 | 93 | 207 |

`ORPHAN_RECORD` and `CORPORATE_ACTION` have zero rows here by design:
orphan synthetic records have no `trade_id` to key `root_cause_labels` on
(they live in `reconciliation/fuzzy_match_*.csv` instead, Step 5), and
this project's real trades are crypto spot trades with no equities-style
corporate actions — both disclosed, not oversights.

## Priority rule (disclosed judgment call)

A trade can be broken on a field *and* late at the same stage. Rather
than pick one arbitrarily, `crosswalk()` reports a single `root_cause_category`
by priority (`MISSING_RECORD > REFERENCE_DATA > QUANTITY > PRICING > TIMING > CLEAN`)
plus a separate `has_timing_issue` flag that can be `True` alongside any
category — so a `PRICING` break that also arrived late is visible as
both, not forced into one label.

---

## Classification (Step 7): rule-based vs. ML

Two classifiers predict `root_cause_category` from **observable fields
only** — `price_diff_pct`, `quantity_diff_pct`, `side_match`,
`match_status`, `lifecycle_status` — never `injected_break_type`, which
exists solely as the evaluation target. Run: `rule_based_classifier.py`,
`ml_classifier.py`, then `compare_classifiers.py`.

- **Rule-based** (`rule_based_classifier.py`): a hand-written decision
  tree mirroring Step 6's priority order, using the same 0.01% tolerance
  as the matching engine. Deterministic, scored on the full 22,016 rows.
- **ML** (`ml_classifier.py`): XGBoost multiclass, 70/30 stratified
  train/test split, one-hot categorical features. Scored on its 6,605-row
  held-out test set only (never seen during training).

| | accuracy | rows scored | misses |
|---|---:|---:|---:|
| Rule-based | 99.90% | 22,016 | 21 |
| ML (XGBoost) | 99.88% | 6,605 (test split) | 8 |

**Not a perfectly matched comparison** — different row counts, disclosed
rather than smoothed over (`compare_classifiers.py`'s docstring). What
*is* directly comparable: all 8 of the ML classifier's misses are among
the rule-based classifier's 21 misses on the same rows — both approaches
fail on exactly the same underlying cases, not different ones.

### Both classifiers' misses, fully explained (not just "close enough")

Every miss is a `TIMING → CLEAN` error, split into two distinct, verified
causes:

1. **8 rows: no lifecycle signal exists at all.** The trade never reached
   the `settled` lifecycle stage (gated at an earlier stage per Step 3's
   design), so there is no `lifecycle_events` row to read a status from —
   a genuine information limit, not a modeling gap either classifier
   could close from observable fields alone.
2. **13 rows: the delay is real but absorbed by a looser deadline.** The
   clearing statement genuinely arrived late relative to its *normal
   processing lag* (the `timing_breach` injection pushes it 1–3 days out
   — data/synthetic/README.md), but the `settled` stage's `expected_by`
   target is the real T+1 *settlement* convention, which — spanning a
   weekend in this trade set — leaves several days of slack. E.g.
   `coinbase:1073146400`'s clearing statement arrived 2026-08-22, three
   days after the trade, yet T+1 from confirmation landed on
   2026-08-24 (Monday) — so `lifecycle_events.status` correctly reads
   `on_time` even though the record was operationally anomalous. Verified
   directly against both CSVs, not inferred.

This is a genuine, disclosed conceptual gap, not a bug: this project's
only observable timing signal is *settlement-SLA breach*
(`lifecycle_events.status`), which is a much looser bar than *unusually
slow processing relative to a normal-lag baseline*. Catching case 2 would
need "time since trade at receipt, relative to the disclosed normal lag
range" exposed as its own feature — a natural extension, noted here
rather than silently omitted.

### Honest framing on rules vs. ML

Near-parity between the two approaches is the **expected** result here,
not a disappointing one. This project's synthetic breaks are
deterministic and mutually exclusive by construction
(`data/synthetic/generate_synthetic_records.py`), so `root_cause_category`
is close to an exact function of the observable features — there's no
hidden nonlinear pattern for gradient boosting to find that a hand-written
rule can't already express. What this comparison actually demonstrates is
that the labeling pipeline is internally consistent end-to-end (both
independently-built classifiers converge on the same ~99.9% answer, and
fail on the same disclosed edge cases) — not that ML has no value over
rules in general. Real trade data, with genuine noise and overlapping
break causes, is where that comparison would actually differentiate the
two approaches; that's out of scope for what this project's data can show.

### ML feature importance

`lifecycle_status_breached` (0.193), `quantity_diff_pct` (0.181), and
`price_diff_pct` (0.179) dominate — consistent with the rule-based
priority order, and reassuring: the model learned to lean on the same
signals the hand-written rules were given priority over, not something
spurious. `match_status_missing` and `stage_*` have ~zero importance,
because `match_status='missing'` alone perfectly determines
`MISSING_RECORD` — there's nothing left for other features to explain
once that value is known.

### Scope note

Predictions/comparisons here are kept as file artifacts
(`*_predictions.csv`, `*_summary.json`), not loaded into a new SQL table —
unlike Steps 2–6, this step is an analysis/evaluation exercise on top of
the already-persisted `root_cause_labels` ground truth, not a new part of
the core data model. Step 17 (Results & Honest Comparison) is where this
comparison gets surfaced project-wide.
