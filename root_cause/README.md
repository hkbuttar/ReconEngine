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
