 validation load: real trades + synthetic clearing/confirm CSVs
-- into the schema, via staging tables + BULK INSERT. Not the full -- ETL (no data-quality checks / ingestion audit yet) -- this just proves
-- the schema holds real data end-to-end. Assumes trades_real.csv,
-- clearing_statements.csv, exchange_confirms.csv are already copied to
-- /tmp/ inside the container (see ingestion/load_to_sql_server.sh).

CREATE TABLE stg_trades (
    venue NVARCHAR(20), native_trade_id NVARCHAR(40), agg_trade_id NVARCHAR(40), symbol NVARCHAR(20),
    side NVARCHAR(4), price NVARCHAR(40), quantity NVARCHAR(40), traded_at NVARCHAR(50)
);
CREATE TABLE stg_clearing (
    trade_id_ref NVARCHAR(60), clearing_ref NVARCHAR(40), reported_venue NVARCHAR(20),
    reported_symbol NVARCHAR(20), reported_side NVARCHAR(4), reported_price NVARCHAR(40),
    reported_quantity NVARCHAR(40), statement_date NVARCHAR(20), received_at NVARCHAR(50),
    is_synthetic NVARCHAR(5), injected_break_type NVARCHAR(30)
);
CREATE TABLE stg_confirms (
    trade_id_ref NVARCHAR(60), confirm_ref NVARCHAR(40), reported_venue NVARCHAR(20),
    reported_symbol NVARCHAR(20), reported_side NVARCHAR(4), reported_price NVARCHAR(40),
    reported_quantity NVARCHAR(40), confirm_timestamp NVARCHAR(50), received_at NVARCHAR(50),
    is_synthetic NVARCHAR(5), injected_break_type NVARCHAR(30)
);
GO

BULK INSERT stg_trades FROM '/tmp/trades_real.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
BULK INSERT stg_clearing FROM '/tmp/clearing_statements.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
BULK INSERT stg_confirms FROM '/tmp/exchange_confirms.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

INSERT INTO trades (venue, native_trade_id, symbol, side, price, quantity, traded_at)
SELECT venue, native_trade_id, symbol, side, CAST(price AS DECIMAL(18,8)), CAST(quantity AS DECIMAL(18,8)), CAST(CONVERT(DATETIMEOFFSET, traded_at, 127) AS DATETIME2)
FROM stg_trades;
GO

INSERT INTO clearing_statements
    (trade_id, clearing_ref, reported_venue, reported_symbol, reported_side, reported_price, reported_quantity, statement_date, received_at, injected_break_type)
SELECT
    t.trade_id, c.clearing_ref, c.reported_venue, c.reported_symbol, c.reported_side,
    CAST(c.reported_price AS DECIMAL(18,8)), CAST(c.reported_quantity AS DECIMAL(18,8)),
    CAST(c.statement_date AS DATE), CAST(CONVERT(DATETIMEOFFSET, c.received_at, 127) AS DATETIME2), c.injected_break_type
FROM stg_clearing c
LEFT JOIN trades t
    ON t.venue = CASE WHEN c.trade_id_ref = '' THEN NULL ELSE LEFT(c.trade_id_ref, CHARINDEX(':', c.trade_id_ref) - 1) END
   AND t.native_trade_id = CASE WHEN c.trade_id_ref = '' THEN NULL ELSE SUBSTRING(c.trade_id_ref, CHARINDEX(':', c.trade_id_ref) + 1, 100) END;
GO

INSERT INTO exchange_confirms
    (trade_id, confirm_ref, reported_venue, reported_symbol, reported_side, reported_price, reported_quantity, confirm_timestamp, received_at, injected_break_type)
SELECT
    t.trade_id, x.confirm_ref, x.reported_venue, x.reported_symbol, x.reported_side,
    CAST(x.reported_price AS DECIMAL(18,8)), CAST(x.reported_quantity AS DECIMAL(18,8)),
    CAST(CONVERT(DATETIMEOFFSET, x.confirm_timestamp, 127) AS DATETIME2), CAST(CONVERT(DATETIMEOFFSET, x.received_at, 127) AS DATETIME2), x.injected_break_type
FROM stg_confirms x
LEFT JOIN trades t
    ON t.venue = CASE WHEN x.trade_id_ref = '' THEN NULL ELSE LEFT(x.trade_id_ref, CHARINDEX(':', x.trade_id_ref) - 1) END
   AND t.native_trade_id = CASE WHEN x.trade_id_ref = '' THEN NULL ELSE SUBSTRING(x.trade_id_ref, CHARINDEX(':', x.trade_id_ref) + 1, 100) END;
GO

DROP TABLE stg_trades;
DROP TABLE stg_clearing;
DROP TABLE stg_confirms;
GO

SELECT 'trades' AS tbl, COUNT(*) AS n FROM trades
UNION ALL SELECT 'clearing_statements', COUNT(*) FROM clearing_statements
UNION ALL SELECT 'exchange_confirms', COUNT(*) FROM exchange_confirms;
GO
