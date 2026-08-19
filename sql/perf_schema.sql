-- Step 13: standalone performance-testing tables, structurally identical
-- to trades/clearing_statements/reconciliation_results but namespaced
-- perf_* so volume testing never touches the live project data.

DROP TABLE IF EXISTS perf_reconciliation_results;
DROP TABLE IF EXISTS perf_clearing_statements;
DROP TABLE IF EXISTS perf_trades;
GO

CREATE TABLE perf_trades (
    trade_id        BIGINT IDENTITY(1,1) PRIMARY KEY,
    venue           NVARCHAR(20)   NOT NULL,
    native_trade_id NVARCHAR(40)   NOT NULL,
    symbol          NVARCHAR(20)   NOT NULL,
    side            NVARCHAR(4)    NOT NULL,
    price           DECIMAL(18,8)  NOT NULL,
    quantity        DECIMAL(18,8)  NOT NULL,
    traded_at       DATETIME2      NOT NULL,
    CONSTRAINT uq_perf_trades_venue_native UNIQUE (venue, native_trade_id)
);

CREATE TABLE perf_clearing_statements (
    clearing_id       BIGINT IDENTITY(1,1) PRIMARY KEY,
    trade_id          BIGINT NULL REFERENCES perf_trades(trade_id),
    clearing_ref      NVARCHAR(40)  NOT NULL,
    reported_price    DECIMAL(18,8) NOT NULL,
    reported_quantity DECIMAL(18,8) NOT NULL,
    received_at       DATETIME2     NOT NULL
);
GO
