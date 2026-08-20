# Qlik associative data model

`load_script.qvs` loads 12 tables. Qlik's associative engine links tables
by matching field names, so the model's correctness depends entirely on
which fields are left bare (associate) vs. qualified with a table prefix
(don't) — that decision is documented here, not left implicit.

## Deliberately associated (bare field names)

- **`trade_id`** — the hub key. Every fact table (`Trades`,
  `ReconciliationResults`, `RootCauseLabels`, `LifecycleEvents`,
  `Settlements`, `AccountingFeed`, `InvoiceReconciliation`,
  `BreakAgingSummary`, `BreakAgingDaily`) carries it, so selecting one
  trade in any chart filters all the others — this is the whole point of
  using Qlik's associative model rather than a fixed set of pre-joined
  reports (deliberate reuse of the plan's explicit "using Qlik's
  associative data model deliberately" requirement).
- **`stage`** (`'clearing'`/`'confirm'`) — associates
  `ReconciliationResults`, `RootCauseLabels`, `BreakAgingSummary`,
  `BreakAgingDaily`, so filtering to one stage narrows all four
  consistently.
- **`venue`** — associates `Trades` and `InvoiceReconciliation`.
- **`symbol`** — associates within `Trades` only (no other table carries
  it) — included in the unqualify list for forward-compatibility, not
  because it currently links anything.

## Deliberately NOT associated (qualified with a table prefix)

Every other same-named-sounding field is prefixed
(`Lifecycle.Status` vs. `Settlement.Status` vs. `Invoice.MatchStatus` vs.
`Reconciliation.MatchStatus`) specifically because they are **not** the
same concept and must never silently merge:

- `lifecycle_events.status` (`on_time`/`late`/`breached`) vs.
  `settlements.settlement_status` (`pending`/`settled`/...) vs.
  `reconciliation_results.match_status` (`matched`/`broken`/`missing`) vs.
  `invoice_reconciliation.match_status` — four different controlled
  vocabularies that happen to share short generic column names in SQL.
  Qlik would otherwise associate all four into one field, letting a
  filter on `late` (a lifecycle concept) silently also filter
  `invoice_reconciliation` rows, producing a chart that's technically
  rendering but semantically wrong — the single most common real Qlik
  modeling bug, and the reason `QUALIFY *` is the script's second line,
  not an afterthought.

## Unlinked reference tables (by design)

- **`AuditLog`** — kept **unassociated** to `trade_id`. It's an event
  stream referenced by a free-text `entity_ref` (sometimes
  `"trade_id|stage"`, sometimes a `source_name` string — `audit_log` schema is intentionally heterogeneous across event types).
  Forcing it into the trade-centric star would require parsing that
  composite key back apart in the load script for a benefit only the
  Compliance sheet needs occasionally — browsed on its own table instead.
- **`LineageEdges`** — table-level, not row-level. Deliberately has no `trade_id` at
  all; the Lineage sheet reads it as a static reference list, not a
  filterable fact table.

## Shape

```
                    Trades (hub: trade_id, venue, symbol)
                       |
        +--------------+-------------+------------------+-------------------+
        |              |             |                  |                   |
ReconciliationResults  RootCauseLabels  LifecycleEvents  InvoiceReconciliation  Settlements
   (stage)               (stage)                                                AccountingFeed
        |              |
   BreakAgingSummary  BreakAgingDaily
      (stage)            (stage)

AuditLog        -- unlinked, browsed independently
LineageEdges    -- unlinked, static reference
Alerts          -- unlinked (entity_ref is free text, same reasoning as AuditLog)
```
