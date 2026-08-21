-- populate: alerts, ported from monitoring/alert_rules.py's rule logic.
-- alert_rules.py itself shells out to `docker exec ... sqlcmd`, which
-- isn't available inside this container, so the underlying INSERT...
-- SELECT statements are reused directly here instead of the Python
-- orchestration layer around them. Same four rules, same thresholds.

INSERT INTO alerts (alert_type, severity, entity_ref, description, threshold_breached)
SELECT 'CRITICAL_AGED_BREAK', 'critical',
       CAST(trade_id AS NVARCHAR(20)) + '|' + stage,
       'Break still open at TIER4_CRITICAL_AGED (14+ days unresolved): ' + root_cause_category,
       'age >= 14 days'
FROM break_aging_summary
WHERE max_escalation_tier_reached = 'TIER4_CRITICAL_AGED' AND still_open_at_window_end = 1;

INSERT INTO alerts (alert_type, severity, entity_ref, description, threshold_breached)
SELECT 'MATERIAL_INVOICE_DISCREPANCY', 'warning',
       CAST(trade_id AS NVARCHAR(20)),
       'Invoice line discrepant by $' + CAST(delta_usd AS NVARCHAR(30)) +
       ' (' + injected_discrepancy_type + ', ' + venue + ')',
       'abs(delta) > $10 OR relative > 50%'
FROM invoice_reconciliation
WHERE match_status = 'discrepant'
  AND (ABS(delta_usd) > 10.0
       OR ABS(delta_usd) / NULLIF(expected_fee_usd, 0) > 0.5);

INSERT INTO alerts (alert_type, severity, entity_ref, description, threshold_breached)
SELECT 'LOW_MATCH_RATE', 'critical', stage,
       'Match rate for stage ''' + stage + ''' is ' + CAST(match_rate_pct AS NVARCHAR(10)) + '%',
       'match_rate_pct < 85.0'
FROM vw_MatchRateByStage
WHERE match_rate_pct < 85.0;

INSERT INTO alerts (alert_type, severity, entity_ref, description, threshold_breached)
SELECT 'INGESTION_FAILURE', 'critical', source_name,
       'Ingestion run failed: ' + ISNULL(error_message, '(no error message)'),
       'status = failed'
FROM ingestion_audit
WHERE status = 'failed';
