-- Loads lifecycle/{lifecycle_events,settlements,accounting_feed}.csv
-- (Step 3 output) into the schema, same staging-table + BULK INSERT
-- pattern as sql/load_data.sql. Assumes trades is already populated (see
-- that script) and the 3 CSVs are copied to /tmp/ in the container.

CREATE TABLE stg_lifecycle (
    trade_id_ref NVARCHAR(60), stage_code NVARCHAR(30), entered_at NVARCHAR(50),
    expected_by NVARCHAR(50), status NVARCHAR(20)
);
CREATE TABLE stg_settlements (
    trade_id_ref NVARCHAR(60), expected_settle_date NVARCHAR(20), actual_settle_date NVARCHAR(20),
    settlement_status NVARCHAR(20), settlement_amount NVARCHAR(40), currency NVARCHAR(10)
);
CREATE TABLE stg_accounting (
    trade_id_ref NVARCHAR(60), gl_account NVARCHAR(60), debit_credit NVARCHAR(1),
    amount NVARCHAR(40), currency NVARCHAR(10), posted_at NVARCHAR(50), posting_status NVARCHAR(20)
);
GO

BULK INSERT stg_lifecycle FROM '/tmp/lifecycle_events.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
BULK INSERT stg_settlements FROM '/tmp/settlements.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
BULK INSERT stg_accounting FROM '/tmp/accounting_feed.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

INSERT INTO lifecycle_events (trade_id, stage_code, entered_at, expected_by, status)
SELECT
    t.trade_id, l.stage_code,
    CAST(CONVERT(DATETIMEOFFSET, l.entered_at, 127) AS DATETIME2),
    CASE WHEN l.expected_by = '' THEN NULL ELSE CAST(CONVERT(DATETIMEOFFSET, l.expected_by, 127) AS DATETIME2) END,
    l.status
FROM stg_lifecycle l
JOIN trades t
    ON t.venue = LEFT(l.trade_id_ref, CHARINDEX(':', l.trade_id_ref) - 1)
   AND t.native_trade_id = SUBSTRING(l.trade_id_ref, CHARINDEX(':', l.trade_id_ref) + 1, 100);
GO

INSERT INTO settlements (trade_id, expected_settle_date, actual_settle_date, settlement_status, settlement_amount, currency)
SELECT
    t.trade_id, CAST(s.expected_settle_date AS DATE), CAST(s.actual_settle_date AS DATE),
    s.settlement_status, CAST(s.settlement_amount AS DECIMAL(18,2)), s.currency
FROM stg_settlements s
JOIN trades t
    ON t.venue = LEFT(s.trade_id_ref, CHARINDEX(':', s.trade_id_ref) - 1)
   AND t.native_trade_id = SUBSTRING(s.trade_id_ref, CHARINDEX(':', s.trade_id_ref) + 1, 100);
GO

INSERT INTO accounting_feed (trade_id, gl_account, debit_credit, amount, currency, posted_at, posting_status)
SELECT
    t.trade_id, a.gl_account, a.debit_credit, CAST(a.amount AS DECIMAL(18,2)), a.currency,
    CAST(CONVERT(DATETIMEOFFSET, a.posted_at, 127) AS DATETIME2), a.posting_status
FROM stg_accounting a
JOIN trades t
    ON t.venue = LEFT(a.trade_id_ref, CHARINDEX(':', a.trade_id_ref) - 1)
   AND t.native_trade_id = SUBSTRING(a.trade_id_ref, CHARINDEX(':', a.trade_id_ref) + 1, 100);
GO

DROP TABLE stg_lifecycle;
DROP TABLE stg_settlements;
DROP TABLE stg_accounting;
GO

SELECT 'lifecycle_events' AS tbl, COUNT(*) AS n FROM lifecycle_events
UNION ALL SELECT 'settlements', COUNT(*) FROM settlements
UNION ALL SELECT 'accounting_feed', COUNT(*) FROM accounting_feed;
GO
