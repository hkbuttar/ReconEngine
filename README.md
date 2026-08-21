# ReconEngine

Post-trade reconciliation on real trade fills and fee schedules, with
disclosed synthetic discrepancy injection. Full lifecycle state machine,
high-volume performance testing, industry-grounded root-cause taxonomy,
data lineage, and a Qlik Sense BI layer on SQL Server. LLM-assisted.

## Motivation

Every prior project in this series (`streamalpha`, `bookmaker`, `execedge`,
`marketforge`) answers "what should we trade" or "how risky is our book."
This project answers a different, equally real question: did the trade
that happened match what everyone thinks happened, at every stage from
capture to settlement, and if not, why. Built to speak directly to
operations/BI job postings' named tools and responsibilities: Qlik Sense,
SQL Server, full trade lifecycle support, audit trail reporting, invoice
reconciliation, and AI-assisted workflow automation.

## Data

See [`data/real/README.md`](data/real/README.md) for the precise
real-vs-synthetic disclosure. Summary:

- **Real**: ~11,000 real trades pulled live from Binance, Coinbase, and
  Kraken's public market-data APIs (`data/real/trades_real.csv`), real
  published maker/taker fee schedules for those three venues
  (`data/real/fee_schedules.py`), and the real US equities T+1 settlement
  convention (`data/real/settlement_rules.py`).
- **Synthetic (disclosed)**: `clearing_statements.csv` and
  `exchange_confirms.csv` under `data/synthetic/`, derived from the real
  trades above with ~13% of rows per stage carrying a labeled, injected
  discrepancy (missing/orphan/price/quantity/timing/side breaks) — see
  [`data/synthetic/README.md`](data/synthetic/README.md) for exact rates
  and rationale. No public source publishes internal system-to-system
  trade mismatches, so this is the one generated layer in the project.

## Repo structure

```
reconengine/
├── data/               # real trade fills, real fee schedules, real settlement rules, synthetic discrepancies
├── ingestion/             # ETL from front-office, clearing firm, exchange sources into SQL Server
├── lifecycle/                # state machine: capture -> clearing -> confirm -> settle -> accounting
├── reconciliation/               # matching engine, break detection, per-stage checks
├── root_cause/                       # industry-grounded taxonomy, rule-based + ML classification
├── llm_assist/                           # LLM break explanations, natural-language query
├── invoice_recon/                            # real fee schedule vs. synthetically perturbed invoice
├── aging/                                        # multi-day rolling recon, break carry-forward, escalation
├── audit_trail/                                      # immutable audit log, regulatory-format reporting
├── lineage/                                              # source-to-dashboard data lineage tracking
├── performance/                                              # volume/load testing, throughput benchmarks
├── monitoring/                                                   # SLA tracking, observability, alerting
├── sql/                                                              # SQL Server schema, procs, views
├── qlik/                                                                # Qlik Sense app, load scripts
├── backend/                                                                # FastAPI
├── notebooks/                                                                  # research.ipynb
├── tests/
├── requirements.txt
└── README.md
```

## Results & Honest Comparison

Every figure below is a real number pulled from this project's own live
database, test suite, or benchmark output — not illustrative or rounded
for effect. Sourced from each area's own README, cross-checked against
the live DB and the test suite (`tests/`) rather than restated from
memory.

### Match rates

| stage | matched | broken | missing | match rate |
|---|---:|---:|---:|---:|
| clearing | 10,012 | 769 | 227 | 90.95% |
| confirm | 10,078 | 723 | 207 | 91.55% |

(`reconciliation/README.md`, `sql/monitoring_views.sql`'s `vw_MatchRateByStage`)

### Rule-based vs. ML root-cause classification

| | accuracy | rows scored |
|---|---:|---:|
| Rule-based | 99.90% | 22,016 (full set) |
| ML (XGBoost) | 99.88% | 6,605 (held-out test split) |

Both classifiers fail on the **exact same 8 rows** — not different ones —
each fully explained (not hand-waved) as trades with no observable
lifecycle signal at all (gated before reaching that stage). Near-parity
is the expected result here: this project's breaks are deterministic and
mutually exclusive by construction, so there's no hidden nonlinear
pattern for gradient boosting to find that a hand-written rule can't
already express (`root_cause/README.md`'s "Classification" section, which
also covers the ML feature-importance finding: the model independently
learned to lean on the same signals the rules were given priority over).

### Break aging & resolution

| outcome | count | % |
|---|---:|---:|
| resolved same day | 1,039 | 39.9% |
| resolved in 1–2 days | 795 | 30.6% |
| resolved in 3–7 days | 513 | 19.7% |
| never resolved (14-day window) | 254 | 9.8% |

Rolling open-break count declines from 1,562 (day 0) to a flat 254
(days 6–14) — the 254 plateau *is* the never-resolved cohort, aging
straight through to `TIER4_CRITICAL_AGED` (`aging/README.md`).

### Invoice discrepancy detection

| venue | discrepancy rate | net $ impact |
|---|---:|---:|
| binance | 7.36% | +$16.03 |
| coinbase | 7.28% | +$499.96 |
| kraken | 6.25% | +$1,377.64 |

**100% of genuine discrepancies caught** (`double_billed` 216/216,
`rate_misapplied` 204/204) after fixing a real bug found during this
project: an absolute-only materiality threshold let 509 of them through
unflagged on tiny-notional trades, fixed with a combined absolute+relative
rule (`invoice_recon/README.md`).

### Measured throughput

| | value | context |
|---|---:|---|
| Matching engine | 452,610 trades/sec | real code, not a stand-in benchmark |
| SQL load (BULK INSERT + join) | ~133,000 rows/sec | server-side timed, ~400K rows end to end |

The matching engine's raw throughput is not the real bottleneck at any
plausible volume — SQL load is (`performance/README.md`, including a
documented case where a hypothesized query optimization was tested and
**honestly reported as not working**, with the actual cause diagnosed via
the real execution plan rather than assumed).

### Lineage completeness

18/18 coded lineage edges present in the live `lineage_events` table, 0
orphan nodes, 0 cycles, every synthetic table traces back to the real
trades — all verified by `tests/test_lineage_completeness.py`, not just
asserted in `lineage/graph.py`'s design doc.

### What rests on real data, and what that means for how far this generalizes

**Real, throughout**: the trades themselves (price, quantity, side, real
trade IDs from three venues' live APIs), the fee schedules, the T+1
settlement convention, every FIX Protocol / SWIFT MT548 / Reg SHO
citation grounding the taxonomy and aging design.

**Synthetic, disclosed at the point each is introduced**: the
clearing/confirm discrepancies themselves (`data/synthetic/README.md`),
the invoice "actual received" side (`invoice_recon/README.md`), each
break's resolution date (`aging/README.md`) — in every case because no
public source publishes what real firms' internal mismatches or
remediation timelines actually look like, the same reason those
mismatches are valuable enough for reconciliation teams to keep private
in the first place.

**What this means concretely**: the *mechanics* proven here — a
tolerance-based matching engine that scores 100% against its own ground
truth, a taxonomy crosswalk grounded in real industry citations, an
aging/escalation model, a genuinely immutable audit log, a rule-based/ML
classifier comparison — are validated against real trade data and would
carry over to a live desk's actual reconciliation problem. The *specific
numbers* above (90.95% match rate, 9.8% never-resolved, etc.) are
artifacts of this project's disclosed injection rates, not a claim about
what any real firm's break rate looks like. A reader should take the
architecture and the rigor as the transferable result, and the exact
percentages as illustrative of a system exercised end-to-end on real
data, not as a benchmark for any real operations team to compare against.

## Limitations

Restated plainly, not buried in each area's own README:

- **The synthetic boundary is real and load-bearing.** Every number that
  depends on the clearing/confirm discrepancy layer, the invoice "actual
  received" side, or a break's resolution date rests on disclosed,
  synthetically generated data — not because the mechanics are fake, but
  because no public source publishes what real firms' internal mismatches
  or remediation timelines look like (`data/synthetic/README.md`).
  Nothing here should be read as "this is what a real trading desk's
  break rate is."
- **Every tolerance and threshold is a disclosed judgment call, calibrated
  against this project's own data — not an industry standard.** The
  0.01% matching tolerance, the $0.01/10% invoice materiality rule, the
  85% low-match-rate alert floor, the aging escalation tiers (loosely
  adapted from Reg SHO, not a literal transplant) — all chosen to be
  large enough to exercise the mechanism and small enough not to mask a
  genuine break, on this dataset specifically.
- **The real trade data is a modest, single-asset-class sample**: ~11,000
  crypto spot trades over roughly 7 minutes of live market activity, not
  an independent high-volume dataset. The 200,000-trade performance
  benchmark scales it via disclosed replication (real price/quantity/side,
  synthetic ids) — a real technique for load-testing the pipeline's
  mechanics, not evidence of what real daily volume looks like.
- **Performance numbers are specific to the hardware they were measured
  on** — SQL Server 2022 running under x86 emulation on Apple Silicon,
  documented in `sql/README.md` and `performance/README.md`. A native
  deployment would likely be faster; not measured here.
- **The taxonomy and settlement citations are grounded in equities/
  traditional-finance conventions (SEC T+1, FIX Protocol, SWIFT MT548,
  Reg SHO) applied to crypto trade data** — a disclosed, deliberate
  cross-domain choice (`data/real/settlement_rules.py`), not a claim that
  crypto trades actually settle T+1 or that these citations are
  crypto-specific.
- **The Qlik dashboard is fully specified but only partially confirmed
  live.** The load script, data model, and all 4 sheets are built and
  documented (`qlik/README.md`); getting it running end to end depends on
  your own Qlik Cloud account and is still in progress as of this
  writing.
- **The `pyodbc` production DB path was verified over Docker's local
  bridge network, not over the open internet against a real Azure SQL
  instance** (`DEPLOYMENT.md`) — the connection string is the only thing
  that would change, but that specific configuration hasn't been
  exercised.
- **LLM-assisted features depend on a third-party API** (Claude) whose
  behavior isn't pinned or version-locked beyond the model ID used —
  outputs are explicitly disclosed as assistive, not authoritative
  (`llm_assist/README.md`), and re-running the same prompt later isn't
  guaranteed to produce byte-identical output.

## Future Work

- **Real-time streaming ingestion** via the same Kafka infrastructure
  already built in `streamalpha` (this project family's sibling repo) —
  the natural next step from this project's batch-oriented ingestion
  pipeline to something that reconciles trades as they happen, not after
  the fact.
- **Multi-currency / multi-asset-class support.** Every trade here is a
  USD-quoted (or USDT, treated 1:1) crypto spot trade — extending to
  equities, FX, or multiple settlement currencies would exercise the
  currency-conversion and cross-asset-class edges this project's single-
  asset-class data never touches.
- **Expanded regulatory reporting format coverage.** The exception report
  (`audit_trail/exception_report.py`) is structurally grounded in SWIFT
  MT548's coded-reason-field precedent, but only one MT548 code (`NMAS`)
  was independently verified during this build — a real next step would
  verify the rest of that code list (or the equivalent FIX/ISO 20022
  vocabulary) directly rather than reusing this project's own taxonomy
  codes in that structural role.
- **A real firm partnership for genuinely proprietary validation data,**
  if one ever became accessible — the one thing that would let this
  project's matching/taxonomy/aging mechanics be validated against real
  clearing-firm and exchange-confirmation mismatches instead of the
  necessarily-disclosed-synthetic layer this build is anchored to.
- **A tighter or ML-assisted fuzzy-match resolution.** The matching
  engine's own finding (`reconciliation/README.md`) was that a 5%/1-hour fuzzy-match
  tolerance is loose enough to spuriously match almost anything in a
  dense real trade tape — a real improvement here would be a learned
  matcher (or a much tighter, deliberately-tuned tolerance) rather than
  the fixed-tolerance heuristic used now.

## Status

- [x] **Environment & Data Acquisition.** Real trade data pulled
      (`ingestion/acquire_real_trades.py`), real fee schedules and
      settlement rules documented (`data/real/`). See disclosure above.
- [x] **SQL Server Schema Design.** Full T-SQL DDL for 9 tables
      (`sql/schema.sql`), stored procedures (`sql/procs.sql`), views
      (`sql/views.sql`), ER diagram (`sql/README.md`). Synthetic
      `clearing_statements`/`exchange_confirms` generated from the real
      trades (`data/synthetic/generate_synthetic_records.py`). Validated
      against a live SQL Server 2022 instance in Docker — all ~11,000
      real trades plus synthetic clearing/confirm records loaded and
      queryable end-to-end. See `sql/README.md` "Status".
- [x] **End-to-End Trade Lifecycle State Machine.**
      `lifecycle/state_machine.py` derives all 5 stages for every real
      trade from the synthetic records, gated (not optimistic) on
      confirmation; validated against the live DB — 431/11,008 trades
      correctly stall before `posted_to_accounting`. See `lifecycle/README.md`.
- [x] **Multi-Source Ingestion (ETL).** `ingestion/run_pipeline.py`
      validates (schema/type/duplicate/referential checks) then loads each
      of the 3 sources independently, idempotently, with a full
      `ingestion_audit` trail. Verified live: clean run loads
      11,008/10,891/10,911 rows; immediate rerun loads 0 (idempotent);
      unit-checked that bad rows (dup keys, bad side, negative price,
      unparseable date, dangling ref) are actually rejected. See
      `ingestion/README.md`.
- [x] **Reconciliation Matching Engine.** `reconciliation/matching_engine.py`
      classifies every (trade, stage) pair matched/broken/missing with
      tolerance-based field matching, scores itself against the synthetic
      ground-truth labels (100% accuracy after fixing a real precision-floor
      bug found by that scoring), and fuzzy-matches orphan records on a
      composite key. Loaded into `reconciliation_results`. See
      `reconciliation/README.md`.
- [x] **Industry-Grounded Root-Cause Taxonomy.** `root_cause/taxonomy.py`
      defines 8 categories cited to FIX Protocol (`OrdRejReason`,
      `ExecRestatementReason`) verified live against fixtrading.org, plus
      the SEC T+1 citation; crosswalks signals onto them.
      Loaded into `root_cause_labels` — this is ground truth.
      See `root_cause/README.md`.
- [x] **Rule-Based & ML-Assisted Root-Cause Classification.**
      Both classifiers predict from observable fields only (never the
      ground-truth label): rule-based 99.90% (22,016 rows), XGBoost
      99.88% (6,605-row test split) — both fail on the exact same 8 rows,
      fully explained (not hand-waved) as two distinct, verified causes.
      See `root_cause/README.md`'s "Classification" section.
- [x] **LLM-Assisted Break Explanation & Natural-Language Query.**
      `llm_assist/break_explainer.py` (Haiku 4.5) explains genuinely
      ambiguous cases (multi-candidate fuzzy matches, timing-within-SLA
      edge cases) from structured facts only, always disclosed as
      assistive. `llm_assist/nl_query.py` (Sonnet 5) translates questions
      to read-only SQL with two independent safety layers. Both live-
      tested against the real DB and a real API key. See `llm_assist/README.md`.
- [x] **Invoice Reconciliation.** `invoice_recon/generate_invoice.py`
      computes expected fees from real trade notional against the real,
      cited fee schedules, compares to a synthetically perturbed
      "received invoice." Found and fixed two real bugs: a materiality
      threshold that let 509 genuine discrepancies slip through on
      tiny-notional trades (fixed with a combined absolute+relative
      rule), and the same scientific-notation bug hit earlier in the
      synthetic-record generator. Loaded into
      `invoice_reconciliation`. See `invoice_recon/README.md`.
- [x] **Multi-Day Rolling Reconciliation with Break Aging.**
      `aging/break_aging.py` runs all 2,601 breaks through 15 daily
      cycles over real calendar dates (disclosed constraint: real trade
      data spans one real day, so dates are real but used as simulated
      checkpoints), with a disclosed synthetic resolution-date
      distribution and escalation tiers adapted from Reg SHO Rule 204.
      Live rolling trend: 1,562 → 254 open breaks, plateauing exactly at
      the disclosed 10% never-resolved rate. See `aging/README.md`.
- [x] **Audit Trail & Regulatory-Format Reporting.**
      `audit_log` is a SQL Server 2022 native append-only LEDGER table —
      immutability enforced by the engine itself, live-verified (`UPDATE`/
      `DELETE` both fail with error 37359, even `DROP TABLE` preserves
      history). Populated with 5,746 real pipeline events. Exception
      report structurally grounded in SWIFT MT548's real coded reason-field
      precedent, verified live. See `audit_trail/README.md`.
- [x] **Data Lineage Tracking.** Explicitly reuses MarketForge's
      validated design (asset-level graph, not row/column-level, disclosed
      scope decision): `lineage/graph.py`'s 13-node/18-edge DAG, exported
      as durable JSON and loaded into `lineage_events`. `lineage/trace.py`
      closes the row-level gap on demand — live-tested, walks one real
      trade's actual data through all 10 tables with correct real/synthetic
      labeling at every hop. See `lineage/README.md`.
- [x] **Volume & Performance Testing.** Scaled real trade data
      to 200,000 trades via disclosed replication (real price/quantity/side,
      synthetic ids). Matching engine: 452,610 trades/sec (not the real
      bottleneck). SQL load: ~400K rows in ~3.0s server-side. Found a real
      2.5× CPU cost in the production join pattern, tested a fix, **honestly
      reported it didn't work**, and diagnosed the actual cause via the
      real execution plan (SQL Server already uses a Hash Match join, not
      a seek — the fix targeted the wrong mechanism). See `performance/README.md`.
- [x] **Monitoring, Observability & Alerting.** 4 monitoring
      views (`sql/monitoring_views.sql`) computed live: 90.95%/91.55%
      match rate, 254 critical-aged breaks, 6.25–7.36% invoice discrepancy
      rate. `monitoring/alert_rules.py` fires 4 disclosed threshold rules
      into a mutable `alerts` table — deliberately a higher bar than the
      break/materiality thresholds themselves, with 2 rules genuinely
      un-triggered (not faked) since real data doesn't breach them. See
      `monitoring/README.md`.
- [~] **Qlik Sense Dashboard.** Fully specified: real load
      script (`qlik/load_script.qvs`) with deliberate associative-model
      discipline, data model design, and all 4 sheets (Accounting,
      Compliance, Operations, Lineage) specified against real, verified
      numbers. **Not running live** — verified Qlik Sense Desktop has no
      macOS support; needs a Qlik Cloud account (your call) to actually
      run. See `qlik/README.md`.
- [x] **Testing & Validation.** 70 tests, all passing: matching engine,
      state machine transitions, taxonomy crosswalk, invoice reconciliation
      (specifically regression-tests the materiality bug found and fixed),
      schema constraints, audit trail immutability, lineage completeness,
      and a performance regression baseline. DB-dependent tests skip
      gracefully (not fail) without the container. Found and fixed 3 real
      test-harness bugs along the way. See `tests/README.md`.
- [x] **Results & Honest Comparison.** Every real number from across the
      project consolidated into one place — match rates, classifier
      accuracy, aging/resolution distribution, invoice detection rate,
      measured throughput, lineage completeness — plus a plain statement
      of what's real vs. disclosed-synthetic and what that boundary means
      for how far the results generalize. See "Results & Honest
      Comparison" above, and `notebooks/research.ipynb` for the same
      findings as an executable notebook (41 cells, 0 errors,
      independently verified end to end) plus a dedicated section
      cataloging every real bug found and fixed across the build.
- [x] **Backend (FastAPI).** 11 endpoints — NL query, 5 monitoring/alert
      endpoints, lineage graph + per-trade trace, trade/break lookups —
      all live-tested against the real DB. Found and fixed a real bug
      during testing: an alert's own data contained the delimiter used to
      parse `sqlcmd` output, silently dropping 254 rows (438 → 692 after
      the fix). See `backend/README.md`.
- [x] **Deployment.** Actually live, not just built: SQL Server on Fly.io
      (`fly.toml`, `sql/deploy/`, self-initializing on first boot) and the
      FastAPI backend on Render (`Dockerfile` + `render.yaml`, real
      `pyodbc` in production). Real hosted endpoint returns real numbers:
      `curl https://reconengine-backend.onrender.com/monitoring/match-rate`
      → 90.95%/91.55%, identical to every other verification in this
      project. Render private services turned out unable to run SQL
      Server at all (a platform capability restriction, not a bug here —
      documented as a dead end in `DEPLOYMENT.md`); Fly.io's microVMs
      don't have that restriction. Found and fixed 4 real bugs getting
      here: a Debian repo signing mismatch, an opaque 500 on missing
      config, a schema-corrupting regex from an earlier cleanup pass, and
      the `alerts` table silently never being populated in the deploy
      image (its source script shells out to a `docker exec` that isn't
      available in production). Full path in `DEPLOYMENT.md`.
- [x] **README.** Expanded with Results & Honest Comparison, Limitations
      (the synthetic boundary restated plainly, every threshold as a
      disclosed judgment call, hardware-specific performance numbers),
      and Future Work (streaming ingestion, multi-asset-class support,
      deeper regulatory format coverage, a real-firm validation
      partnership, a tighter fuzzy-match resolution) — this file, complete.

Every item on this project's original build plan is complete. The one
open thread is the live Qlik Cloud dashboard (`qlik/README.md`) — fully
specified and being connected interactively, not something scriptable
from here. Everything else in the Status list above is built, live-
tested against real data, and documented in its own directory's README.
