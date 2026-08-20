-- ReconEngine SQL Server schema.
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

-- Lifecycle state machine.
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

-- Minimal lineage capture; expanded in lineage/.
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
CREATE INDEX ix_lineage_source ON lineage_events(source_table, source_pk);: one row per ingestion run (ingestion/run_pipeline.py), tracking
-- pre-load data-quality outcomes alongside actual DB load counts. Feeds (lineage) and monitoring: ingestion success/failure rate.
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
CREATE INDEX ix_ingestion_audit_source ON ingestion_audit(source_name, started_at);: matching engine output (reconciliation/matching_engine.py).
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
CREATE INDEX ix_reconciliation_status ON reconciliation_results(stage, match_status);: industry-grounded root-cause labels (root_cause/taxonomy.py),
-- crosswalked from reconciliation_results + lifecycle_events. Ground
-- truth for rule-based vs. ML classifier comparison.
CREATE TABLE root_cause_labels (
    label_id            BIGINT IDENTITY(1,1) PRIMARY KEY,
    trade_id             BIGINT NOT NULL REFERENCES trades(trade_id),
    stage                NVARCHAR(20) NOT NULL CHECK (stage IN ('clearing','confirm')),
    root_cause_category  NVARCHAR(30) NOT NULL,
    has_timing_issue     BIT NOT NULL,
    match_status         NVARCHAR(20) NOT NULL,
    injected_break_type  NVARCHAR(30) NULL,
    lifecycle_status      NVARCHAR(20) NULL,
    computed_at           DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_root_cause_trade_stage UNIQUE (trade_id, stage)
);
CREATE INDEX ix_root_cause_category ON root_cause_labels(root_cause_category);: invoice reconciliation (invoice_recon/generate_invoice.py).
-- Expected fee computed from real trade notional against real published
-- fee schedules (data/real/fee_schedules.py); actual_fee_usd is the
-- synthetically perturbed "received invoice" side. actual_fee_usd/delta_usd
-- NULL means missing_line (trade never billed at all).
CREATE TABLE invoice_reconciliation (
    invoice_line_id       BIGINT IDENTITY(1,1) PRIMARY KEY,
    trade_id               BIGINT NOT NULL UNIQUE REFERENCES trades(trade_id),
    venue                   NVARCHAR(20) NOT NULL,
    notional                DECIMAL(18,8) NOT NULL,
    taker_fee_bps_applied   DECIMAL(9,4) NOT NULL,
    expected_fee_usd        DECIMAL(18,8) NOT NULL,
    actual_fee_usd          DECIMAL(18,8) NULL,
    delta_usd               DECIMAL(18,8) NULL,
    match_status            NVARCHAR(20) NOT NULL CHECK (match_status IN ('matched','discrepant','missing')),
    injected_discrepancy_type NVARCHAR(30) NOT NULL,
    computed_at              DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX ix_invoice_venue_status ON invoice_reconciliation(venue, match_status);: multi-day rolling reconciliation with break aging
-- (aging/break_aging.py). break_aging_daily is the rolling view (one row
-- per break per observation date while still open); break_aging_summary
-- is the aggregate view (one row per break, final resolution outcome).
-- origin_date/observation_date are real calendar dates used as simulated
-- "as of" checkpoints -- see aging/break_aging.py's module docstring for
-- why (the real trade data spans a single real day).
CREATE TABLE break_aging_daily (
    snapshot_id          BIGINT IDENTITY(1,1) PRIMARY KEY,
    trade_id              BIGINT NOT NULL REFERENCES trades(trade_id),
    stage                 NVARCHAR(20) NOT NULL,
    root_cause_category   NVARCHAR(30) NOT NULL,
    origin_date            DATE NOT NULL,
    observation_date       DATE NOT NULL,
    age_days                INT NOT NULL,
    escalation_tier          NVARCHAR(30) NOT NULL,
    CONSTRAINT uq_aging_daily UNIQUE (trade_id, stage, observation_date)
);
CREATE INDEX ix_aging_daily_observation ON break_aging_daily(observation_date, escalation_tier);

CREATE TABLE break_aging_summary (
    summary_id                   BIGINT IDENTITY(1,1) PRIMARY KEY,
    trade_id                      BIGINT NOT NULL REFERENCES trades(trade_id),
    stage                         NVARCHAR(20) NOT NULL,
    root_cause_category           NVARCHAR(30) NOT NULL,
    origin_date                    DATE NOT NULL,
    resolved_date                   DATE NULL,
    resolution_days                 INT NULL,
    still_open_at_window_end          BIT NOT NULL,
    max_escalation_tier_reached        NVARCHAR(30) NOT NULL,
    CONSTRAINT uq_aging_summary_trade_stage UNIQUE (trade_id, stage)
);
CREATE INDEX ix_aging_summary_open ON break_aging_summary(still_open_at_window_end, max_escalation_tier_reached);: immutable, append-only audit log -- architecturally enforced
-- via SQL Server 2022's native LEDGER feature, not an application-level
-- convention. Live-verified in this project (sql/README.md "Status"):
-- UPDATE and DELETE against an append-only ledger table both fail with
-- engine error 37359 ("Updates are not allowed for the append only
-- Ledger table"), and even DROP TABLE doesn't erase history -- SQL
-- Server renames it to a tracked MSSQL_DroppedLedgerTable_* system table.
CREATE TABLE audit_log (
    audit_log_id  BIGINT IDENTITY(1,1) PRIMARY KEY,
    event_type    NVARCHAR(40)  NOT NULL,
    entity_type   NVARCHAR(40)  NOT NULL,
    entity_ref    NVARCHAR(60)  NULL,
    event_at      DATETIME2     NOT NULL,
    details       NVARCHAR(MAX) NULL,
    recorded_at   DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
) WITH (LEDGER = ON (APPEND_ONLY = ON));
CREATE INDEX ix_audit_log_event ON audit_log(event_type, event_at);: alerts triggered by monitoring/alert_rules.py, scanning the
-- live schema against disclosed thresholds. Mutable (unlike audit_log) --
-- alerts get acknowledged in real ops, an audit log entry never should.
CREATE TABLE alerts (
    alert_id           BIGINT IDENTITY(1,1) PRIMARY KEY,
    alert_type          NVARCHAR(40)  NOT NULL,
    severity             NVARCHAR(20)  NOT NULL CHECK (severity IN ('info','warning','critical')),
    entity_ref            NVARCHAR(60)  NULL,
    description             NVARCHAR(500) NOT NULL,
    threshold_breached        NVARCHAR(200) NULL,
    triggered_at                DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    acknowledged                  BIT NOT NULL DEFAULT 0
);
CREATE INDEX ix_alerts_type_severity ON alerts(alert_type, severity, acknowledged);
