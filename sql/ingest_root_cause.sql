 load: root_cause_labels (root_cause/taxonomy.py output). Same
-- temp-table + idempotent-anti-join pattern as sql/ingest_*.sql.

CREATE TABLE #stg_root_cause (
    trade_id_ref NVARCHAR(60), stage NVARCHAR(20), root_cause_category NVARCHAR(30),
    has_timing_issue NVARCHAR(10), match_status NVARCHAR(20), injected_break_type NVARCHAR(30),
    lifecycle_status NVARCHAR(20)
);
GO

BULK INSERT #stg_root_cause FROM '/tmp/root_cause_labels.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

INSERT INTO root_cause_labels (trade_id, stage, root_cause_category, has_timing_issue, match_status, injected_break_type, lifecycle_status)
SELECT
    t.trade_id, r.stage, r.root_cause_category,
    CASE WHEN r.has_timing_issue = 'True' THEN 1 ELSE 0 END,
    r.match_status, NULLIF(r.injected_break_type, ''), NULLIF(r.lifecycle_status, '')
FROM #stg_root_cause r
JOIN trades t
    ON t.venue = LEFT(r.trade_id_ref, CHARINDEX(':', r.trade_id_ref) - 1)
   AND t.native_trade_id = SUBSTRING(r.trade_id_ref, CHARINDEX(':', r.trade_id_ref) + 1, 100)
WHERE NOT EXISTS (
    SELECT 1 FROM root_cause_labels existing WHERE existing.trade_id = t.trade_id AND existing.stage = r.stage
);
GO
