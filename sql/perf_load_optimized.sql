-- Optimized version of the clearing_statements load. The
-- CHARINDEX/SUBSTRING string-parsing embedded directly in the JOIN
-- predicate (sql/perf_load.sql, and every ingest_*.sql in production) is
-- non-sargable -- SQL Server can't use perf_trades' (venue,
-- native_trade_id) unique index for an index seek when the predicate is
-- a computed expression evaluated per candidate row pair, rather than a
-- plain column comparison.
--
-- Fix: split trade_id_ref into two real columns in a single UPDATE pass
-- over the staging table (O(n), once) BEFORE joining, so the join itself
-- is a plain equi-join SQL Server's optimizer can execute as an index
-- seek/hash join against the real index -- the same total string-parsing
-- work, just moved out of the join predicate.

CREATE TABLE #stg_perf_clearing2 (
    trade_id_ref NVARCHAR(60), clearing_ref NVARCHAR(40), reported_venue NVARCHAR(20),
    reported_symbol NVARCHAR(20), reported_side NVARCHAR(4), reported_price NVARCHAR(40),
    reported_quantity NVARCHAR(40), statement_date NVARCHAR(20), received_at NVARCHAR(50),
    is_synthetic NVARCHAR(5), injected_break_type NVARCHAR(30)
);
GO

SET STATISTICS TIME ON;
GO

PRINT '--- BULK INSERT: perf_clearing2 staging ---';
BULK INSERT #stg_perf_clearing2 FROM '/tmp/volume_clearing_statements.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

-- Added only after BULK INSERT completes -- adding them to the staging
-- table up front breaks BULK INSERT's positional column mapping to the
-- 11-column CSV (the exact bug this project already hit earlier --
-- data/synthetic/README.md's ROWTERMINATOR fix, same "IID_IColumnsInfo"
-- error class).
ALTER TABLE #stg_perf_clearing2 ADD venue_ref NVARCHAR(20), native_id_ref NVARCHAR(40);
GO

PRINT '--- UPDATE: pre-split trade_id_ref into real columns (once, O(n)) ---';
UPDATE #stg_perf_clearing2
SET venue_ref = CASE WHEN trade_id_ref = '' THEN NULL ELSE LEFT(trade_id_ref, CHARINDEX(':', trade_id_ref) - 1) END,
    native_id_ref = CASE WHEN trade_id_ref = '' THEN NULL ELSE SUBSTRING(trade_id_ref, CHARINDEX(':', trade_id_ref) + 1, 100) END;
GO

PRINT '--- INSERT...SELECT: perf_clearing_statements (sargable equi-join) ---';
INSERT INTO perf_clearing_statements (trade_id, clearing_ref, reported_price, reported_quantity, received_at)
SELECT
    t.trade_id, c.clearing_ref, CAST(c.reported_price AS DECIMAL(18,8)), CAST(c.reported_quantity AS DECIMAL(18,8)),
    CAST(CONVERT(DATETIMEOFFSET, c.received_at, 127) AS DATETIME2)
FROM #stg_perf_clearing2 c
LEFT JOIN perf_trades t
    ON t.venue = c.venue_ref AND t.native_trade_id = c.native_id_ref;
GO

SET STATISTICS TIME OFF;
GO

DROP TABLE #stg_perf_clearing2;
GO
