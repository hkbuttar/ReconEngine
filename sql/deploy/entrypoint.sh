#!/bin/bash
# Starts SQL Server, then self-initializes the reconengine database on
# first boot only -- schema, procs, views, then the full real+synthetic
# data load, in the exact order sql/README.md documents for local dev.
# On every later restart (persistent disk keeps the data directory), the
# `reconengine` database already exists, so this whole block is skipped
# and SQL Server just starts normally -- idempotent across restarts, not
# just idempotent within a single load run (the ingest_*.sql scripts'
# own anti-join idempotency, reused here, but that's a different property
# from "don't reload gigabytes of data and re-append the audit log on
# every restart").
set -e

/opt/mssql/bin/sqlservr &
SQLSERVR_PID=$!

SQLCMD=/opt/mssql-tools18/bin/sqlcmd
SA_PASSWORD="${MSSQL_SA_PASSWORD}"

echo "Waiting for SQL Server to accept connections..."
for i in $(seq 1 60); do
    if $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -Q "SELECT 1" >/dev/null 2>&1; then
        echo "SQL Server is ready after ${i}s"
        break
    fi
    sleep 2
done

DB_EXISTS=$($SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -h -1 -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM sys.databases WHERE name = 'reconengine';" | tr -d '[:space:]')

if [ "$DB_EXISTS" = "1" ]; then
    echo "reconengine database already exists -- skipping init, this is a restart."
else
    echo "First boot -- initializing reconengine database."
    INIT_DIR=/usr/src/reconengine-init

    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -Q "CREATE DATABASE reconengine;"
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/schema.sql"
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/procs.sql"
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/views.sql"
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/monitoring_views.sql"

    # Real + synthetic data, in the load-order sql/README.md documents.
    cp "$INIT_DIR/data/real/trades_real.csv" /tmp/trades_real.csv
    cp "$INIT_DIR/data/synthetic/clearing_statements.csv" /tmp/clearing_statements.csv
    cp "$INIT_DIR/data/synthetic/exchange_confirms.csv" /tmp/exchange_confirms.csv
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/ingest_trades.sql"
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/ingest_clearing.sql"
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/ingest_confirms.sql"

    cp "$INIT_DIR/lifecycle/lifecycle_events.csv" /tmp/lifecycle_events.csv
    cp "$INIT_DIR/lifecycle/settlements.csv" /tmp/settlements.csv
    cp "$INIT_DIR/lifecycle/accounting_feed.csv" /tmp/accounting_feed.csv
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/load_lifecycle.sql"

    cp "$INIT_DIR/reconciliation/reconciliation_results.csv" /tmp/reconciliation_results.csv
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/ingest_reconciliation.sql"

    cp "$INIT_DIR/root_cause/root_cause_labels.csv" /tmp/root_cause_labels.csv
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/ingest_root_cause.sql"

    cp "$INIT_DIR/invoice_recon/invoice_reconciliation.csv" /tmp/invoice_reconciliation.csv
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/ingest_invoice.sql"

    cp "$INIT_DIR/aging/break_aging_daily.csv" /tmp/break_aging_daily.csv
    cp "$INIT_DIR/aging/break_aging_summary.csv" /tmp/break_aging_summary.csv
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/ingest_aging.sql"

    cp "$INIT_DIR/audit_trail/audit_events.csv" /tmp/audit_events.csv
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/ingest_audit_log.sql"

    cp "$INIT_DIR/lineage/lineage_events.csv" /tmp/lineage_events.csv
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/ingest_lineage.sql"

    # alerts: monitoring/alert_rules.py's rule logic, ported to plain SQL
    # (see sql/populate_alerts.sql) since that script's own docker-exec
    # sqlcmd path isn't available inside this container. Runs last since
    # it reads from break_aging_summary, invoice_reconciliation, and
    # vw_MatchRateByStage, all populated by the steps above.
    $SQLCMD -S localhost -U sa -P "$SA_PASSWORD" -C -d reconengine -i "$INIT_DIR/sql/populate_alerts.sql"

    echo "reconengine database initialized."
fi

wait $SQLSERVR_PID
