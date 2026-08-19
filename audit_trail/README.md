# audit_trail/ — Audit Trail & Regulatory-Format Reporting (Step 11)

## Immutable audit log

`audit_log` is a SQL Server 2022 native **append-only LEDGER table**
(`WITH (LEDGER = ON (APPEND_ONLY = ON))`, `sql/schema.sql`) — immutability
is enforced by the database engine itself, not an application-level
convention (a trigger, a revoked GRANT, "please don't update this
table"). **Live-verified in this project, against the real populated
table**, not just the empty DDL:

```sql
UPDATE audit_log SET details = 'tampered' WHERE audit_log_id = 1;
-- Msg 37359: Updates are not allowed for the append only Ledger table 'audit_log'.

DELETE FROM audit_log WHERE audit_log_id = 1;
-- Msg 37359: Updates are not allowed for the append only Ledger table 'audit_log'.
```

Even more striking, tested on a throwaway table before trusting it on the
real one: `DROP TABLE` doesn't erase a ledger table's history either —
SQL Server renames it to a tracked `MSSQL_DroppedLedgerTable_*` system
table rather than deleting it.

`audit_trail/build_audit_log.py` populates it from this project's own
**real, already-computed** pipeline activity — not placeholder events:

| event_type | count | source |
|---|---:|---|
| `INGESTION_RUN` | 3 | Step 4's real ingestion runs |
| `BREAK_IDENTIFIED` | 2,601 | Step 6's non-`CLEAN` root-cause labels |
| `BREAK_RESOLVED` | 2,347 | Step 10's aging simulation |
| `INVOICE_DISCREPANCY_IDENTIFIED` | 795 | Step 9's non-`matched` invoice lines |

`sql/ingest_audit_log.sql` loads it — no idempotent anti-join here
(unlike every other `ingest_*.sql`): an append-only audit trail is
supposed to accumulate, not be deduplicated against itself. Rerunning it
appends a second full history, by design.

## Exception report

`exception_report.py` exports a **Trade Break / Exception Report**
(`exception_report.csv`) — one row per break, joining
`root_cause_labels` (category), `break_aging_summary` (age/status), and
`invoice_reconciliation` (financial impact, where applicable).

**Real structural precedent, verified live**: SWIFT ISO 15022 message
type **MT548** (Settlement Status and Processing Advice) uses a dedicated
Reason Code field (24B) carrying a controlled vocabulary of structured
break/status reasons — verified directly at
iotafinance.com/en/SWIFT-ISO15022-View-Code-NMAS.html (code `NMAS`, "No
Matching Started"). This report does **not** claim to emit valid MT548
messages — MT548 covers one settlement instruction's status, not a
multi-category exception report, and this project doesn't reuse MT548's
exact codes since the rest of that code list wasn't independently
verified in this pass (disclosed rather than guessed at). What's grounded
in the real precedent is the *structure*: a coded reason field with a
controlled vocabulary is standard real industry practice, not invented
here — so the report uses ReconEngine's own real, cited taxonomy codes
(`root_cause/taxonomy.py`, Step 6) in that same role.

### Result

2,601 breaks reported: 254 `OPEN` (all `TIER4_CRITICAL_AGED`), 2,347
`RESOLVED`. 124 rows carry a `financial_impact_usd` figure — a
**coincidental** overlap, not a causal one: reconciliation breaks
(Step 6) and invoice discrepancies (Step 9) are independently generated
with separate seeded randomness, so a trade appearing in both just means
it happened to draw an injected break in each independent process, not
that one caused the other.
