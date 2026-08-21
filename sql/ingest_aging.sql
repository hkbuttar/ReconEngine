-- load: break_aging_daily + break_aging_summary
-- (aging/break_aging.py output). Same temp-table + idempotent-anti-join
-- pattern as sql/ingest_*.sql.

CREATE TABLE #stg_aging_daily (
    trade_id_ref NVARCHAR(60), stage NVARCHAR(20), root_cause_category NVARCHAR(30),
    origin_date NVARCHAR(20), observation_date NVARCHAR(20), age_days NVARCHAR(10), escalation_tier NVARCHAR(30)
);
CREATE TABLE #stg_aging_summary (
    trade_id_ref NVARCHAR(60), stage NVARCHAR(20), root_cause_category NVARCHAR(30),
    origin_date NVARCHAR(20), resolved_date NVARCHAR(20), resolution_days NVARCHAR(10),
    still_open_at_window_end NVARCHAR(10), max_escalation_tier_reached NVARCHAR(30)
);
GO

BULK INSERT #stg_aging_daily FROM '/tmp/break_aging_daily.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
BULK INSERT #stg_aging_summary FROM '/tmp/break_aging_summary.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

INSERT INTO break_aging_daily (trade_id, stage, root_cause_category, origin_date, observation_date, age_days, escalation_tier)
SELECT
    t.trade_id, d.stage, d.root_cause_category, CAST(d.origin_date AS DATE), CAST(d.observation_date AS DATE),
    CAST(d.age_days AS INT), d.escalation_tier
FROM #stg_aging_daily d
JOIN trades t
    ON t.venue = LEFT(d.trade_id_ref, CHARINDEX(':', d.trade_id_ref) - 1)
   AND t.native_trade_id = SUBSTRING(d.trade_id_ref, CHARINDEX(':', d.trade_id_ref) + 1, 100)
WHERE NOT EXISTS (
    SELECT 1 FROM break_aging_daily existing WHERE existing.trade_id = t.trade_id AND existing.stage = d.stage AND existing.observation_date = CAST(d.observation_date AS DATE)
);
GO

INSERT INTO break_aging_summary (trade_id, stage, root_cause_category, origin_date, resolved_date, resolution_days, still_open_at_window_end, max_escalation_tier_reached)
SELECT
    t.trade_id, s.stage, s.root_cause_category, CAST(s.origin_date AS DATE),
    CASE WHEN s.resolved_date = '' THEN NULL ELSE CAST(s.resolved_date AS DATE) END,
    CASE WHEN s.resolution_days = '' THEN NULL ELSE CAST(s.resolution_days AS INT) END,
    CASE WHEN s.still_open_at_window_end = 'True' THEN 1 ELSE 0 END,
    s.max_escalation_tier_reached
FROM #stg_aging_summary s
JOIN trades t
    ON t.venue = LEFT(s.trade_id_ref, CHARINDEX(':', s.trade_id_ref) - 1)
   AND t.native_trade_id = SUBSTRING(s.trade_id_ref, CHARINDEX(':', s.trade_id_ref) + 1, 100)
WHERE NOT EXISTS (
    SELECT 1 FROM break_aging_summary existing WHERE existing.trade_id = t.trade_id AND existing.stage = s.stage
);
GO
