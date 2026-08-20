-- Performance-testing load, same BULK INSERT + CHARINDEX-join
-- pattern as sql/ingest_trades.sql / sql/ingest_clearing.sql (the actual
-- production loading code), against perf_trades/perf_clearing_statements
-- at volume. SET STATISTICS TIME ON reports SQL Server's own measured
-- CPU/elapsed time per statement, precise server-side numbers rather
-- than wall-clock timing that also includes docker exec/subprocess
-- dispatch overhead.

SET STATISTICS TIME ON;
GO

CREATE TABLE #stg_perf_trades (
    venue NVARCHAR(20), native_trade_id NVARCHAR(40), symbol NVARCHAR(20),
    side NVARCHAR(4), price NVARCHAR(40), quantity NVARCHAR(40), traded_at NVARCHAR(50)
);
GO

PRINT '--- BULK INSERT: perf_trades staging ---';
BULK INSERT #stg_perf_trades FROM '/tmp/volume_trades.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

PRINT '--- INSERT...SELECT: perf_trades (cast + real insert) ---';
INSERT INTO perf_trades (venue, native_trade_id, symbol, side, price, quantity, traded_at)
SELECT venue, native_trade_id, symbol, side, CAST(price AS DECIMAL(18,8)), CAST(quantity AS DECIMAL(18,8)),
       CAST(CONVERT(DATETIMEOFFSET, traded_at, 127) AS DATETIME2)
FROM #stg_perf_trades;
GO

CREATE TABLE #stg_perf_clearing (
    trade_id_ref NVARCHAR(60), clearing_ref NVARCHAR(40), reported_venue NVARCHAR(20),
    reported_symbol NVARCHAR(20), reported_side NVARCHAR(4), reported_price NVARCHAR(40),
    reported_quantity NVARCHAR(40), statement_date NVARCHAR(20), received_at NVARCHAR(50),
    is_synthetic NVARCHAR(5), injected_break_type NVARCHAR(30)
);
GO

PRINT '--- BULK INSERT: perf_clearing staging ---';
BULK INSERT #stg_perf_clearing FROM '/tmp/volume_clearing_statements.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

PRINT '--- INSERT...SELECT: perf_clearing_statements (CHARINDEX-based join, production pattern) ---';
INSERT INTO perf_clearing_statements (trade_id, clearing_ref, reported_price, reported_quantity, received_at)
SELECT
    t.trade_id, c.clearing_ref, CAST(c.reported_price AS DECIMAL(18,8)), CAST(c.reported_quantity AS DECIMAL(18,8)),
    CAST(CONVERT(DATETIMEOFFSET, c.received_at, 127) AS DATETIME2)
FROM #stg_perf_clearing c
LEFT JOIN perf_trades t
    ON t.venue = CASE WHEN c.trade_id_ref = '' THEN NULL ELSE LEFT(c.trade_id_ref, CHARINDEX(':', c.trade_id_ref) - 1) END
   AND t.native_trade_id = CASE WHEN c.trade_id_ref = '' THEN NULL ELSE SUBSTRING(c.trade_id_ref, CHARINDEX(':', c.trade_id_ref) + 1, 100) END;
GO

DROP TABLE #stg_perf_trades;
DROP TABLE #stg_perf_clearing;
GO

SET STATISTICS TIME OFF;
GO

SELECT 'perf_trades' AS tbl, COUNT(*) AS n FROM perf_trades
UNION ALL SELECT 'perf_clearing_statements', COUNT(*) FROM perf_clearing_statements;
GO
