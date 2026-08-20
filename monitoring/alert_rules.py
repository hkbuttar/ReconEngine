"""Scans the live schema against disclosed alerting thresholds
and writes triggered alerts to `alerts`. All DB access goes through
`docker exec reconengine-sql sqlcmd` -- same environment constraint as
ingestion/run_pipeline.py (no local ODBC driver, see sql/README.md).

Alerting thresholds are deliberately a HIGHER bar than the materiality/
break thresholds that flag something as broken in the first place -- not every break needs to page someone. That distinction is a
disclosed judgment call: a materiality threshold decides what counts as a
break at all; an alerting threshold decides what's urgent enough to
surface, and conflating the two would either alert on everything (noise)
or nothing (missed the point of a break threshold existing).

Rules:
  - CRITICAL_AGED_BREAK: a break_aging_summary row still open at
    TIER4_CRITICAL_AGED.
  - MATERIAL_INVOICE_DISCREPANCY: a discrepant invoice line where the
    dollar impact exceeds $10 absolute OR 50% relative to the expected
    fee -- notably higher than $0.01/10% materiality bar for
    "discrepant" at all, since paging someone over a $0.02 fee error
    would be pure noise.
  - LOW_MATCH_RATE: any reconciliation stage's match rate drops below
    85% -- calibrated against this project's own observed baseline
    (~91% currently), not an industry figure; picked below the current
    baseline so the rule doesn't spuriously fire on normal operation,
    while still being a real, meaningful floor.
  - INGESTION_FAILURE: any ingestion_audit run with status='failed'.
    Zero currently -- included and left un-triggered rather than
    fabricating a failure to demonstrate it, consistent with this
    project's practice of not manufacturing findings.
"""

from __future__ import annotations

import subprocess

CONTAINER = "reconengine-sql"
SA_PASSWORD = "ReconEngine!2026"
SQLCMD = ["docker", "exec", CONTAINER, "/opt/mssql-tools18/bin/sqlcmd",
          "-S", "localhost", "-U", "sa", "-P", SA_PASSWORD, "-C", "-d", "reconengine"]

LOW_MATCH_RATE_THRESHOLD_PCT = 85.0
MATERIAL_INVOICE_ABS_USD = 10.0
MATERIAL_INVOICE_REL_PCT = 0.5


def _sql_escape(value: str) -> str:
    return value.replace("'", "''")


def run_query(query: str) -> str:
    result = subprocess.run(SQLCMD + ["-Q", query], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"sqlcmd query failed: {result.stdout}\n{result.stderr}")
    return result.stdout


def clear_alerts() -> None:
    run_query("DELETE FROM alerts;")


def rule_critical_aged_breaks() -> str:
    return """
    INSERT INTO alerts (alert_type, severity, entity_ref, description, threshold_breached)
    SELECT 'CRITICAL_AGED_BREAK', 'critical',
           CAST(trade_id AS NVARCHAR(20)) + '|' + stage,
           'Break still open at TIER4_CRITICAL_AGED (14+ days unresolved): ' + root_cause_category,
           'age >= 14 days'
    FROM break_aging_summary
    WHERE max_escalation_tier_reached = 'TIER4_CRITICAL_AGED' AND still_open_at_window_end = 1;
    """


def rule_material_invoice_discrepancy() -> str:
    return f"""
    INSERT INTO alerts (alert_type, severity, entity_ref, description, threshold_breached)
    SELECT 'MATERIAL_INVOICE_DISCREPANCY', 'warning',
           CAST(trade_id AS NVARCHAR(20)),
           'Invoice line discrepant by $' + CAST(delta_usd AS NVARCHAR(30)) +
           ' (' + injected_discrepancy_type + ', ' + venue + ')',
           'abs(delta) > ${MATERIAL_INVOICE_ABS_USD} OR relative > {int(MATERIAL_INVOICE_REL_PCT*100)}%'
    FROM invoice_reconciliation
    WHERE match_status = 'discrepant'
      AND (ABS(delta_usd) > {MATERIAL_INVOICE_ABS_USD}
           OR ABS(delta_usd) / NULLIF(expected_fee_usd, 0) > {MATERIAL_INVOICE_REL_PCT});
    """


def rule_low_match_rate() -> str:
    return f"""
    INSERT INTO alerts (alert_type, severity, entity_ref, description, threshold_breached)
    SELECT 'LOW_MATCH_RATE', 'critical', stage,
           'Match rate for stage ''' + stage + ''' is ' + CAST(match_rate_pct AS NVARCHAR(10)) + '%',
           'match_rate_pct < {LOW_MATCH_RATE_THRESHOLD_PCT}'
    FROM vw_MatchRateByStage
    WHERE match_rate_pct < {LOW_MATCH_RATE_THRESHOLD_PCT};
    """


def rule_ingestion_failure() -> str:
    return """
    INSERT INTO alerts (alert_type, severity, entity_ref, description, threshold_breached)
    SELECT 'INGESTION_FAILURE', 'critical', source_name,
           'Ingestion run failed: ' + ISNULL(error_message, '(no error message)'),
           'status = failed'
    FROM ingestion_audit
    WHERE status = 'failed';
    """


def main() -> None:
    clear_alerts()
    for rule in [rule_critical_aged_breaks, rule_material_invoice_discrepancy,
                 rule_low_match_rate, rule_ingestion_failure]:
        run_query(rule())

    summary = run_query(
        "SET NOCOUNT ON; SELECT alert_type, severity, COUNT(*) AS n FROM alerts GROUP BY alert_type, severity ORDER BY alert_type;"
    )
    print(summary)


if __name__ == "__main__":
    main()
