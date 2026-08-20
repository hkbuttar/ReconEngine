# Qlik sheets

Four sheets, each grounded in real numbers already computed and verified
against the live database in earlier steps — not generic placeholder
mockups. Every figure below was queried live, not invented for this spec.

## 1. Accounting

Settlement/P&L/accounting-feed status per stage.

- **KPI tiles**: total settled notional (`Sum(Settlement.AmountUSD)`
  where `Settlement.Status = 'settled'`); total posted to accounting
  (`Sum(Accounting.AmountUSD)` where `Accounting.PostingStatus = 'posted'`,
  10,577 entries); count of trades never reaching accounting
  (11,008 − 10,577 = **431**, disclosed gating result).
- **Bar chart**: `Settlement.Status` distribution over time
  (`Settlement.ActualDate` on the x-axis).
- **Table**: `AccountingFeed` detail, filterable by `Accounting.GLAccount`
  (`{venue}:{symbol}` — e.g. `binance:BTCUSDT`) and `Accounting.DebitCredit`.

## 2. Compliance

Audit trail summary, break aging/escalation, regulatory report status.

- **KPI tiles**: total audit events (5,746); breaks at
  `TIER4_CRITICAL_AGED` (254); resolution-time distribution
  (`same_day` 1,039 / `1_2_days` 795 / `3_7_days` 513 / `unresolved` 254).
- **Line chart**: `BreakAgingDaily`, open-break count over
  `AgingDaily.ObservationDate`, colored by `AgingDaily.EscalationTier` —
  the actual 1,562 → 254 rolling decline from README, live in
  the associative model rather than a static table.
- **Table**: `AuditLog`, filterable by `Audit.EventType`
  (`BREAK_IDENTIFIED` / `BREAK_RESOLVED` / `INVOICE_DISCREPANCY_IDENTIFIED` /
  `INGESTION_RUN`) — the exception report structure from
  `audit_trail/exception_report.py`, browsable live instead of a static
  CSV export.
- **Alert panel**: `Alerts` table, filtered to `Alert.Acknowledged = 0`,
  colored by `Alert.Severity` — 254 `CRITICAL_AGED_BREAK` + 438
  `MATERIAL_INVOICE_DISCREPANCY` currently open.

## 3. Operations

Match rate by stage, break volume by root-cause, invoice reconciliation
status, throughput metrics.

- **KPI tiles**: match rate by stage (clearing 90.95% / confirm 91.55%);
  invoice discrepancy rate by venue (6.25–7.36%);
  matching engine throughput (452,610 trades/sec — a real
  benchmark result, not a placeholder number).
- **Bar chart**: `RootCauseCategory` volume by `stage` — `TIMING` 675 /
  `QUANTITY` 648 / `PRICING` 643 / `MISSING_RECORD` 434 /
  `REFERENCE_DATA` 201.
- **Gauge/KPI**: `Invoice.MatchStatus` distribution per `venue`
  (`InvoiceReconciliation`), net dollar impact
  (`Sum(Invoice.DeltaUSD)`) — kraken +$1,377.64 net.
- **Filter pane**: `stage`, `venue`, `RootCauseCategory` — standard Qlik
  associative selection, so clicking `QUANTITY` on the bar chart
  automatically narrows every other chart on the sheet to matching
  trades (the associative model's actual payoff, not just a data
  connection detail).

## 4. Lineage

Source-to-dashboard traceability, real vs. synthetic clearly labeled.

- **Network/graph visualization** (or, if unavailable, an indented
  table): `LineageEdges` — `Lineage.SourceTable` → `Lineage.TargetTable`,
  colored by `Lineage.IsSyntheticSource` (real = `Trades`/`trades_real.csv`
  only; every other node synthetic-derived, per `lineage/graph.py`).
- **Text tile**: static explanation of the real/synthetic boundary,
  reused verbatim from `data/real/README.md` and
  `data/synthetic/README.md` — this sheet should say the same thing the
  project's own disclosure docs say, not a paraphrase that could drift.
- **Drill-down note**: row-level trace (`lineage/trace.py`) is
  deliberately **not** reproduced as a Qlik object — it's an on-demand
  CLI tool by design, not a
  pre-materialized table Qlik could browse. The sheet documents this
  limitation rather than silently omitting the capability.

## What's not yet live

These are specifications, not screenshots of a running app — see
`qlik/README.md` for why (Qlik Sense Desktop has no macOS support,
verified live) and what happens next.
