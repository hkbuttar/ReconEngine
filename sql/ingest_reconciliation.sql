 load: reconciliation_results (reconciliation/matching_engine.py
-- output). Same temp-table + idempotent-anti-join pattern as
-- sql/ingest_*.sql. Assumes trades is already loaded.

CREATE TABLE #stg_reconciliation (
    trade_id_ref NVARCHAR(60), match_status NVARCHAR(20), price_diff_pct NVARCHAR(20),
    quantity_diff_pct NVARCHAR(20), side_match NVARCHAR(10), injected_break_type NVARCHAR(30),
    stage NVARCHAR(20)
);
GO

BULK INSERT #stg_reconciliation FROM '/tmp/reconciliation_results.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

INSERT INTO reconciliation_results (trade_id, stage, match_status, price_diff_pct, quantity_diff_pct, side_match, injected_break_type)
SELECT
    t.trade_id, r.stage, r.match_status,
    CASE WHEN r.price_diff_pct = '' THEN NULL ELSE CAST(r.price_diff_pct AS DECIMAL(9,4)) END,
    CASE WHEN r.quantity_diff_pct = '' THEN NULL ELSE CAST(r.quantity_diff_pct AS DECIMAL(9,4)) END,
    CASE WHEN r.side_match = '' THEN NULL WHEN r.side_match = 'True' THEN 1 ELSE 0 END,
    NULLIF(r.injected_break_type, '')
FROM #stg_reconciliation r
JOIN trades t
    ON t.venue = LEFT(r.trade_id_ref, CHARINDEX(':', r.trade_id_ref) - 1)
   AND t.native_trade_id = SUBSTRING(r.trade_id_ref, CHARINDEX(':', r.trade_id_ref) + 1, 100)
WHERE NOT EXISTS (
    SELECT 1 FROM reconciliation_results existing WHERE existing.trade_id = t.trade_id AND existing.stage = r.stage
);
GO
