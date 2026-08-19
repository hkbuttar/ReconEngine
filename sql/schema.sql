-- ReconEngine SQL Server schema (Step 2).
-- Target: SQL Server 2019+ / Azure SQL. Not yet executed against a live
-- instance in this environment -- see sql/README.md "Status" section.
--
-- Design: `trades` is the real anchor (data/real/trades_real.csv).
-- `clearing_statements` and `exchange_confirms` are synthetic, derived from
-- it by data/synthetic/generate_synthetic_records.py, with disclosed
-- injected discrepancies -- see data/synthetic/README.md. Both tables
-- allow a NULL trade_id (an "orphan" record: the clearing firm or exchange
-- reports a trade the front office never captured) and a real trade can
-- simply have no matching row in either table (a "missing" break) -- both
-- are real-world break patterns, not schema gaps.

CREATE TABLE trades (
    trade_id        BIGINT IDENTITY(1,1) PRIMARY KEY,
    venue           NVARCHAR(20)   NOT NULL,
    native_trade_id NVARCHAR(40)   NOT NULL,
    symbol          NVARCHAR(20)   NOT NULL,
    side            NVARCHAR(4)    NOT NULL CHECK (side IN ('buy','sell')),
    price           DECIMAL(18,8)  NOT NULL CHECK (price > 0),
    quantity        DECIMAL(18,8)  NOT NULL CHECK (quantity > 0),
    traded_at       DATETIME2      NOT NULL,
    asset_class     NVARCHAR(20)   NOT NULL DEFAULT 'crypto_spot',
    ingested_at     DATETIME2      NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_trades_venue_native UNIQUE (venue, native_trade_id)
);
CREATE INDEX ix_trades_traded_at ON trades(traded_at);
CREATE INDEX ix_trades_symbol_venue ON trades(symbol, venue);

CREATE TABLE clearing_statements (
    clearing_id       BIGINT IDENTITY(1,1) PRIMARY KEY,
    trade_id          BIGINT NULL REFERENCES trades(trade_id),
    clearing_ref      NVARCHAR(40)  NOT NULL UNIQUE,
    reported_venue    NVARCHAR(20)  NOT NULL,
    reported_symbol   NVARCHAR(20)  NOT NULL,
    reported_side     NVARCHAR(4)   NOT NULL CHECK (reported_side IN ('buy','sell')),
    reported_price    DECIMAL(18,8) NOT NULL,
    reported_quantity DECIMAL(18,8) NOT NULL,
    statement_date    DATE          NOT NULL,
    received_at       DATETIME2     NOT NULL,
    is_synthetic      BIT           NOT NULL DEFAULT 1 CHECK (is_synthetic = 1),
    injected_break_type NVARCHAR(30) NOT NULL DEFAULT 'none'
);
CREATE INDEX ix_clearing_trade_id ON clearing_statements(trade_id);

CREATE TABLE exchange_confirms (
    confirm_id        BIGINT IDENTITY(1,1) PRIMARY KEY,
    trade_id          BIGINT NULL REFERENCES trades(trade_id),
    confirm_ref       NVARCHAR(40)  NOT NULL UNIQUE,
    reported_venue    NVARCHAR(20)  NOT NULL,
    reported_symbol   NVARCHAR(20)  NOT NULL,
    reported_side     NVARCHAR(4)   NOT NULL CHECK (reported_side IN ('buy','sell')),
    reported_price    DECIMAL(18,8) NOT NULL,
    reported_quantity DECIMAL(18,8) NOT NULL,
    confirm_timestamp DATETIME2     NOT NULL,
    received_at       DATETIME2     NOT NULL,
    is_synthetic      BIT           NOT NULL DEFAULT 1 CHECK (is_synthetic = 1),
    injected_break_type NVARCHAR(30) NOT NULL DEFAULT 'none'
);
CREATE INDEX ix_confirms_trade_id ON exchange_confirms(trade_id);

CREATE TABLE positions (
    position_id   BIGINT IDENTITY(1,1) PRIMARY KEY,
    venue         NVARCHAR(20)  NOT NULL,
    symbol        NVARCHAR(20)  NOT NULL,
    as_of_date    DATE          NOT NULL,
    net_quantity  DECIMAL(18,8) NOT NULL,
    avg_price     DECIMAL(18,8) NOT NULL,
    updated_at    DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_positions_venue_symbol_date UNIQUE (venue, symbol, as_of_date)
);

CREATE TABLE settlements (
    settlement_id        BIGINT IDENTITY(1,1) PRIMARY KEY,
    trade_id             BIGINT NOT NULL UNIQUE REFERENCES trades(trade_id),
    expected_settle_date DATE          NOT NULL,
    actual_settle_date   DATE          NULL,
    settlement_status    NVARCHAR(20)  NOT NULL DEFAULT 'pending'
        CHECK (settlement_status IN ('pending','settled','failed','cancelled')),
    settlement_amount    DECIMAL(18,2) NOT NULL,
    currency             NVARCHAR(10)  NOT NULL DEFAULT 'USD',
    updated_at           DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);

CREATE TABLE accounting_feed (
    entry_id       BIGINT IDENTITY(1,1) PRIMARY KEY,
    trade_id       BIGINT NOT NULL REFERENCES trades(trade_id),
    gl_account     NVARCHAR(30)  NOT NULL,
    debit_credit   CHAR(1)       NOT NULL CHECK (debit_credit IN ('D','C')),
    amount         DECIMAL(18,2) NOT NULL CHECK (amount >= 0),
    currency       NVARCHAR(10)  NOT NULL DEFAULT 'USD',
    posted_at      DATETIME2     NULL,
    posting_status NVARCHAR(20)  NOT NULL DEFAULT 'pending'
        CHECK (posting_status IN ('pending','posted','rejected')),
    created_at     DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_accounting_trade_id ON accounting_feed(trade_id);

-- Lifecycle state machine (Step 3 populates/transitions this; table lives
-- in the schema from Step 2 since positions/settlements/accounting_feed
-- above all key off it conceptually).
CREATE TABLE lifecycle_stage_ref (
    stage_code  NVARCHAR(30) PRIMARY KEY,
    stage_order INT          NOT NULL UNIQUE,
    description NVARCHAR(200) NOT NULL
);
INSERT INTO lifecycle_stage_ref (stage_code, stage_order, description) VALUES
    ('captured',            1, 'Trade captured from venue/front-office source'),
    ('sent_to_clearing',    2, 'Trade transmitted to clearing firm'),
    ('confirmed',           3, 'Exchange/clearing confirmation received'),
    ('settled',             4, 'Settlement completed'),
    ('posted_to_accounting',5, 'Posted to accounting_feed / general ledger');

CREATE TABLE lifecycle_events (
    event_id    BIGINT IDENTITY(1,1) PRIMARY KEY,
    trade_id    BIGINT       NOT NULL REFERENCES trades(trade_id),
    stage_code  NVARCHAR(30) NOT NULL REFERENCES lifecycle_stage_ref(stage_code),
    entered_at  DATETIME2    NOT NULL,
    expected_by DATETIME2    NULL,
    status      NVARCHAR(20) NOT NULL DEFAULT 'on_time'
        CHECK (status IN ('on_time','late','breached')),
    CONSTRAINT uq_lifecycle_trade_stage UNIQUE (trade_id, stage_code)
);
CREATE INDEX ix_lifecycle_trade_id ON lifecycle_events(trade_id);

-- Minimal lineage capture for Step 2; expanded in Step 12 (lineage/).
CREATE TABLE lineage_events (
    lineage_id          BIGINT IDENTITY(1,1) PRIMARY KEY,
    source_table        NVARCHAR(60)  NOT NULL,
    source_pk           BIGINT        NOT NULL,
    target_table        NVARCHAR(60)  NOT NULL,
    target_pk           BIGINT        NOT NULL,
    transform_step       NVARCHAR(100) NOT NULL,
    is_synthetic_source  BIT           NOT NULL,
    recorded_at          DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_lineage_source ON lineage_events(source_table, source_pk);

-- Step 4: one row per ingestion run (ingestion/run_pipeline.py), tracking
-- pre-load data-quality outcomes alongside actual DB load counts. Feeds
-- Step 12 (lineage) and Step 14 (monitoring: ingestion success/failure rate).
CREATE TABLE ingestion_audit (
    audit_id      BIGINT IDENTITY(1,1) PRIMARY KEY,
    source_name   NVARCHAR(60)  NOT NULL,
    source_file   NVARCHAR(200) NOT NULL,
    started_at    DATETIME2     NOT NULL,
    completed_at  DATETIME2     NULL,
    status        NVARCHAR(20)  NOT NULL DEFAULT 'running'
        CHECK (status IN ('running','succeeded','failed')),
    rows_read     INT NOT NULL DEFAULT 0,
    rows_valid    INT NOT NULL DEFAULT 0,
    rows_rejected INT NOT NULL DEFAULT 0,
    rows_loaded   INT NOT NULL DEFAULT 0,
    quality_check_summary NVARCHAR(MAX) NULL,
    error_message NVARCHAR(MAX) NULL
);
CREATE INDEX ix_ingestion_audit_source ON ingestion_audit(source_name, started_at);

-- Step 5: matching engine output (reconciliation/matching_engine.py).
-- Tolerance-based field matching (price/quantity/side), superseding
-- vw_TradeReconciliationStatus's exact-equality check for anything that
-- needs the real classification. 'missing' rows still carry a real
-- trade_id (this engine always starts from a real trade); orphan records
-- with no real trade at all are handled separately (fuzzy-match CSVs,
-- not persisted here -- see reconciliation/README.md).
CREATE TABLE reconciliation_results (
    result_id           BIGINT IDENTITY(1,1) PRIMARY KEY,
    trade_id             BIGINT NOT NULL REFERENCES trades(trade_id),
    stage                NVARCHAR(20) NOT NULL CHECK (stage IN ('clearing','confirm')),
    match_status         NVARCHAR(20) NOT NULL CHECK (match_status IN ('matched','broken','missing')),
    price_diff_pct       DECIMAL(9,4) NULL,
    quantity_diff_pct    DECIMAL(9,4) NULL,
    side_match           BIT NULL,
    injected_break_type  NVARCHAR(30) NULL,
    computed_at          DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_reconciliation_trade_stage UNIQUE (trade_id, stage)
);
CREATE INDEX ix_reconciliation_status ON reconciliation_results(stage, match_status);
