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

## Status

- [x] **Step 1 — Environment & Data Acquisition.** Real trade data pulled
      (`ingestion/acquire_real_trades.py`), real fee schedules and
      settlement rules documented (`data/real/`). See disclosure above.
- [x] **Step 2 — SQL Server Schema Design.** Full T-SQL DDL for 9 tables
      (`sql/schema.sql`), stored procedures (`sql/procs.sql`), views
      (`sql/views.sql`), ER diagram (`sql/README.md`). Synthetic
      `clearing_statements`/`exchange_confirms` generated from the real
      trades (`data/synthetic/generate_synthetic_records.py`). Validated
      against a live SQL Server 2022 instance in Docker — all ~11,000
      real trades plus synthetic clearing/confirm records loaded and
      queryable end-to-end. See `sql/README.md` "Status".
- [x] **Step 3 — End-to-End Trade Lifecycle State Machine.**
      `lifecycle/state_machine.py` derives all 5 stages for every real
      trade from the Step 2 synthetic records, gated (not optimistic) on
      confirmation; validated against the live DB — 431/11,008 trades
      correctly stall before `posted_to_accounting`. See `lifecycle/README.md`.
- [x] **Step 4 — Multi-Source Ingestion (ETL).** `ingestion/run_pipeline.py`
      validates (schema/type/duplicate/referential checks) then loads each
      of the 3 sources independently, idempotently, with a full
      `ingestion_audit` trail. Verified live: clean run loads
      11,008/10,891/10,911 rows; immediate rerun loads 0 (idempotent);
      unit-checked that bad rows (dup keys, bad side, negative price,
      unparseable date, dangling ref) are actually rejected. See
      `ingestion/README.md`.
- [x] **Step 5 — Reconciliation Matching Engine.** `reconciliation/matching_engine.py`
      classifies every (trade, stage) pair matched/broken/missing with
      tolerance-based field matching, scores itself against the synthetic
      ground-truth labels (100% accuracy after fixing a real precision-floor
      bug found by that scoring), and fuzzy-matches orphan records on a
      composite key. Loaded into `reconciliation_results`. See
      `reconciliation/README.md`.
- [x] **Step 6 — Industry-Grounded Root-Cause Taxonomy.** `root_cause/taxonomy.py`
      defines 8 categories cited to FIX Protocol (`OrdRejReason`,
      `ExecRestatementReason`) verified live against fixtrading.org, plus
      the Step 1 SEC T+1 citation; crosswalks Step 5/3's signals onto them.
      Loaded into `root_cause_labels` — this is Step 7's ground truth.
      See `root_cause/README.md`.
- [x] **Step 7 — Rule-Based & ML-Assisted Root-Cause Classification.**
      Both classifiers predict from observable fields only (never the
      ground-truth label): rule-based 99.90% (22,016 rows), XGBoost
      99.88% (6,605-row test split) — both fail on the exact same 8 rows,
      fully explained (not hand-waved) as two distinct, verified causes.
      See `root_cause/README.md`'s "Classification" section.
- [x] **Step 8 — LLM-Assisted Break Explanation & Natural-Language Query.**
      `llm_assist/break_explainer.py` (Haiku 4.5) explains genuinely
      ambiguous cases (multi-candidate fuzzy matches, timing-within-SLA
      edge cases) from structured facts only, always disclosed as
      assistive. `llm_assist/nl_query.py` (Sonnet 5) translates questions
      to read-only SQL with two independent safety layers. Both live-
      tested against the real DB and a real API key. See `llm_assist/README.md`.
- [ ] Step 9 — Invoice Reconciliation
- [ ] Step 10 — Multi-Day Rolling Reconciliation with Break Aging
- [ ] Step 11 — Audit Trail & Regulatory-Format Reporting
- [ ] Step 12 — Data Lineage Tracking
- [ ] Step 13 — Volume & Performance Testing
- [ ] Step 14 — Monitoring, Observability & Alerting
- [ ] Step 15 — Qlik Sense Dashboard
- [ ] Step 16 — Testing & Validation
- [ ] Step 17 — Results & Honest Comparison
- [ ] Step 18 — Backend (FastAPI)
- [ ] Step 19 — Deployment
- [ ] Step 20 — README (this file, expanded with Results/Limitations/Future Work)

Each unbuilt directory currently holds a stub `README.md` pointing at the
step that will fill it in — see this file's Status list above for what's
next.
