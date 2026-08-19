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
      trades (`data/synthetic/generate_synthetic_records.py`). Not yet
      executed against a live SQL Server instance — see `sql/README.md`
      "Status" (that's Step 19, Deployment).
- [ ] Step 3 — End-to-End Trade Lifecycle State Machine
- [ ] Step 4 — Multi-Source Ingestion (ETL)
- [ ] Step 5 — Reconciliation Matching Engine
- [ ] Step 6 — Industry-Grounded Root-Cause Taxonomy
- [ ] Step 7 — Rule-Based & ML-Assisted Root-Cause Classification
- [ ] Step 8 — LLM-Assisted Break Explanation & Natural-Language Query
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
