-- Step 14: monitoring/observability views. Feed Qlik's Operations view
-- (Step 15) and the FastAPI monitoring endpoint (Step 18) directly --
-- these are the canonical metric definitions both consume, not
-- redefined ad hoc in either place.

CREATE OR ALTER VIEW vw_IngestionHealth AS
SELECT
    source_name,
    COUNT(*) AS total_runs,
    SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded_runs,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
    CAST(100.0 * SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) AS DECIMAL(5,2)) AS success_rate_pct,
    SUM(rows_loaded) AS total_rows_loaded,
    SUM(rows_rejected) AS total_rows_rejected,
    MAX(completed_at) AS last_run_at
FROM ingestion_audit
GROUP BY source_name;
GO

CREATE OR ALTER VIEW vw_MatchRateByStage AS
SELECT
    stage,
    COUNT(*) AS total,
    SUM(CASE WHEN match_status = 'matched' THEN 1 ELSE 0 END) AS matched,
    SUM(CASE WHEN match_status = 'broken' THEN 1 ELSE 0 END) AS broken,
    SUM(CASE WHEN match_status = 'missing' THEN 1 ELSE 0 END) AS missing,
    CAST(100.0 * SUM(CASE WHEN match_status = 'matched' THEN 1 ELSE 0 END) / COUNT(*) AS DECIMAL(5,2)) AS match_rate_pct
FROM reconciliation_results
GROUP BY stage;
GO

CREATE OR ALTER VIEW vw_BreakAgingDistribution AS
SELECT
    max_escalation_tier_reached AS escalation_tier,
    still_open_at_window_end,
    COUNT(*) AS break_count
FROM break_aging_summary
GROUP BY max_escalation_tier_reached, still_open_at_window_end;
GO

CREATE OR ALTER VIEW vw_InvoiceDiscrepancyRate AS
SELECT
    venue,
    COUNT(*) AS total_lines,
    SUM(CASE WHEN match_status <> 'matched' THEN 1 ELSE 0 END) AS discrepant_lines,
    CAST(100.0 * SUM(CASE WHEN match_status <> 'matched' THEN 1 ELSE 0 END) / COUNT(*) AS DECIMAL(5,2)) AS discrepancy_rate_pct,
    SUM(delta_usd) AS net_dollar_impact
FROM invoice_reconciliation
GROUP BY venue;
GO
