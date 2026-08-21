-- load: invoice_reconciliation (invoice_recon/generate_invoice.py
-- output). Same temp-table + idempotent-anti-join pattern as
-- sql/ingest_*.sql.

CREATE TABLE #stg_invoice (
    trade_id_ref NVARCHAR(60), venue NVARCHAR(20), notional NVARCHAR(40),
    taker_fee_bps_applied NVARCHAR(20), expected_fee_usd NVARCHAR(40),
    actual_fee_usd NVARCHAR(40), delta_usd NVARCHAR(40), match_status NVARCHAR(20),
    injected_discrepancy_type NVARCHAR(30)
);
GO

BULK INSERT #stg_invoice FROM '/tmp/invoice_reconciliation.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

INSERT INTO invoice_reconciliation
    (trade_id, venue, notional, taker_fee_bps_applied, expected_fee_usd, actual_fee_usd, delta_usd, match_status, injected_discrepancy_type)
SELECT
    t.trade_id, i.venue, CAST(i.notional AS DECIMAL(18,8)), CAST(i.taker_fee_bps_applied AS DECIMAL(9,4)),
    CAST(i.expected_fee_usd AS DECIMAL(18,8)),
    CASE WHEN i.actual_fee_usd = '' THEN NULL ELSE CAST(i.actual_fee_usd AS DECIMAL(18,8)) END,
    CASE WHEN i.delta_usd = '' THEN NULL ELSE CAST(i.delta_usd AS DECIMAL(18,8)) END,
    i.match_status, i.injected_discrepancy_type
FROM #stg_invoice i
JOIN trades t
    ON t.venue = LEFT(i.trade_id_ref, CHARINDEX(':', i.trade_id_ref) - 1)
   AND t.native_trade_id = SUBSTRING(i.trade_id_ref, CHARINDEX(':', i.trade_id_ref) + 1, 100)
WHERE NOT EXISTS (SELECT 1 FROM invoice_reconciliation existing WHERE existing.trade_id = t.trade_id);
GO
