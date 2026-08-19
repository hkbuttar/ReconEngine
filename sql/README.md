# sql/ — SQL Server Schema Design (Step 2)

## Status

Schema, stored procedures, and views are written and reviewed but **not
yet executed against a live SQL Server instance** — no SQL Server
Express/Azure SQL instance is provisioned in this environment yet. That's
Step 19 (Deployment). To validate/load now:

```bash
# SQL Server Express in Docker (requires Docker running):
docker run -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=<your-password>" \
  -p 1433:1433 --name reconengine-sql -d mcr.microsoft.com/mssql/server:2022-latest

sqlcmd -S localhost -U sa -P '<your-password>' -i sql/schema.sql
sqlcmd -S localhost -U sa -P '<your-password>' -i sql/procs.sql
sqlcmd -S localhost -U sa -P '<your-password>' -i sql/views.sql
```

## Files

- `schema.sql` — DDL for all 9 tables, keys, constraints, indexes.
- `procs.sql` — stored procedures for common reconciliation lookups
  (unmatched records, field mismatches, position recompute).
- `views.sql` — views the Qlik data model (Step 15) will load from.

## ER diagram

```mermaid
erDiagram
    trades ||--o{ clearing_statements : "trade_id (nullable FK)"
    trades ||--o{ exchange_confirms : "trade_id (nullable FK)"
    trades ||--o| settlements : "trade_id"
    trades ||--o{ accounting_feed : "trade_id"
    trades ||--o{ lifecycle_events : "trade_id"
    lifecycle_stage_ref ||--o{ lifecycle_events : "stage_code"

    trades {
        bigint trade_id PK
        nvarchar venue
        nvarchar native_trade_id
        nvarchar symbol
        nvarchar side
        decimal price
        decimal quantity
        datetime2 traded_at
    }
    clearing_statements {
        bigint clearing_id PK
        bigint trade_id FK "nullable: orphan record"
        nvarchar clearing_ref
        decimal reported_price
        decimal reported_quantity
        nvarchar injected_break_type
    }
    exchange_confirms {
        bigint confirm_id PK
        bigint trade_id FK "nullable: orphan record"
        nvarchar confirm_ref
        decimal reported_price
        decimal reported_quantity
        nvarchar injected_break_type
    }
    settlements {
        bigint settlement_id PK
        bigint trade_id FK
        date expected_settle_date
        date actual_settle_date
        nvarchar settlement_status
    }
    accounting_feed {
        bigint entry_id PK
        bigint trade_id FK
        nvarchar gl_account
        char debit_credit
        decimal amount
    }
    lifecycle_stage_ref {
        nvarchar stage_code PK
        int stage_order
    }
    lifecycle_events {
        bigint event_id PK
        bigint trade_id FK
        nvarchar stage_code FK
        datetime2 entered_at
        nvarchar status
    }
    positions {
        bigint position_id PK
        nvarchar venue
        nvarchar symbol
        date as_of_date
        decimal net_quantity
    }
    lineage_events {
        bigint lineage_id PK
        nvarchar source_table
        bigint source_pk
        nvarchar target_table
        bigint target_pk
    }
```

`positions` and `lineage_events` aren't drawn with FK arrows above: both
key off `(venue, symbol)`/arbitrary source-target table pairs rather than
a single `trade_id`, by design — `positions` is an aggregate over many
trades, and `lineage_events` deliberately stays table-agnostic so Step 12
can point it at any table pair without a schema change.

## Design decisions (disclosed)

- **`trade_id` is nullable on `clearing_statements`/`exchange_confirms`.**
  Both "a real trade with no clearing/confirm record at all" (missing
  break) and "a clearing/confirm record with no matching real trade"
  (orphan break — the clearing firm or exchange reports something the
  front office never captured) are real, common break patterns. Making
  the FK nullable represents both without a sentinel row.
- **`injected_break_type` lives directly on the synthetic tables**, not
  only in a side file. Every synthetic row honestly labels what, if
  anything, was perturbed about it and why — see
  `data/synthetic/README.md` for the full disclosure and injection rates.
  A real clearing firm's statement obviously wouldn't carry this column;
  it exists here purely so the synthetic layer is auditable at a glance,
  consistent with this project's disclosure-first design.
- **`DECIMAL(18,8)`** for price/quantity, not `FLOAT` or `MONEY` — crypto
  quantities in `data/real/trades_real.csv` go to 8 decimal places (e.g.
  `0.00000001` BTC); `MONEY`'s 4-decimal precision would silently truncate
  real trade data.
- **Natural key `(venue, native_trade_id)`** on `trades`, not the venue's
  native id alone — the three venues' id spaces aren't guaranteed disjoint
  (e.g. Kraken and Coinbase could each mint an id `"12345"`).
- **No `is_synthetic` column on `trades`** — everything in that table is
  real by construction; the flag only exists on the two synthetic tables,
  where its absence would be the anomaly.
