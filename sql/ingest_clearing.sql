-- per-source load: clearing_statements (clearing firm source).
-- Same temp-table + idempotent anti-join pattern as ingest_trades.sql.
-- Assumes trades has already been ingested (trade_id_ref resolution
-- depends on it).

CREATE TABLE #stg_clearing (
    trade_id_ref NVARCHAR(60), clearing_ref NVARCHAR(40), reported_venue NVARCHAR(20),
    reported_symbol NVARCHAR(20), reported_side NVARCHAR(4), reported_price NVARCHAR(40),
    reported_quantity NVARCHAR(40), statement_date NVARCHAR(20), received_at NVARCHAR(50),
    is_synthetic NVARCHAR(5), injected_break_type NVARCHAR(30)
);
GO

BULK INSERT #stg_clearing FROM '/tmp/clearing_statements.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

INSERT INTO clearing_statements
    (trade_id, clearing_ref, reported_venue, reported_symbol, reported_side, reported_price, reported_quantity, statement_date, received_at, injected_break_type)
SELECT
    t.trade_id, c.clearing_ref, c.reported_venue, c.reported_symbol, c.reported_side,
    CAST(c.reported_price AS DECIMAL(18,8)), CAST(c.reported_quantity AS DECIMAL(18,8)),
    CAST(c.statement_date AS DATE), CAST(CONVERT(DATETIMEOFFSET, c.received_at, 127) AS DATETIME2), c.injected_break_type
FROM #stg_clearing c
LEFT JOIN trades t
    ON t.venue = CASE WHEN c.trade_id_ref = '' THEN NULL ELSE LEFT(c.trade_id_ref, CHARINDEX(':', c.trade_id_ref) - 1) END
   AND t.native_trade_id = CASE WHEN c.trade_id_ref = '' THEN NULL ELSE SUBSTRING(c.trade_id_ref, CHARINDEX(':', c.trade_id_ref) + 1, 100) END
WHERE NOT EXISTS (SELECT 1 FROM clearing_statements existing WHERE existing.clearing_ref = c.clearing_ref);
GO
