 per-source load: exchange_confirms (exchange source). Same
-- pattern as ingest_clearing.sql.

CREATE TABLE #stg_confirms (
    trade_id_ref NVARCHAR(60), confirm_ref NVARCHAR(40), reported_venue NVARCHAR(20),
    reported_symbol NVARCHAR(20), reported_side NVARCHAR(4), reported_price NVARCHAR(40),
    reported_quantity NVARCHAR(40), confirm_timestamp NVARCHAR(50), received_at NVARCHAR(50),
    is_synthetic NVARCHAR(5), injected_break_type NVARCHAR(30)
);
GO

BULK INSERT #stg_confirms FROM '/tmp/exchange_confirms.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

INSERT INTO exchange_confirms
    (trade_id, confirm_ref, reported_venue, reported_symbol, reported_side, reported_price, reported_quantity, confirm_timestamp, received_at, injected_break_type)
SELECT
    t.trade_id, x.confirm_ref, x.reported_venue, x.reported_symbol, x.reported_side,
    CAST(x.reported_price AS DECIMAL(18,8)), CAST(x.reported_quantity AS DECIMAL(18,8)),
    CAST(CONVERT(DATETIMEOFFSET, x.confirm_timestamp, 127) AS DATETIME2), CAST(CONVERT(DATETIMEOFFSET, x.received_at, 127) AS DATETIME2), x.injected_break_type
FROM #stg_confirms x
LEFT JOIN trades t
    ON t.venue = CASE WHEN x.trade_id_ref = '' THEN NULL ELSE LEFT(x.trade_id_ref, CHARINDEX(':', x.trade_id_ref) - 1) END
   AND t.native_trade_id = CASE WHEN x.trade_id_ref = '' THEN NULL ELSE SUBSTRING(x.trade_id_ref, CHARINDEX(':', x.trade_id_ref) + 1, 100) END
WHERE NOT EXISTS (SELECT 1 FROM exchange_confirms existing WHERE existing.confirm_ref = x.confirm_ref);
GO
