# SQL Server, self-initializing on first boot: schema, procs, views, and
# the full real+synthetic data load baked in and run automatically
# (entrypoint.sh), so this is a genuine "deploy and it works" service, not
# one that needs a manual sqlcmd session run against it afterward.
#
# Build context must be the repo root (render.yaml sets dockerContext),
# since this needs the already-committed real/synthetic CSVs alongside
# the sql/ scripts -- not just this directory.
FROM mcr.microsoft.com/mssql/server:2022-latest

USER root

COPY sql/deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Everything entrypoint.sh's init sequence reads from, bundled into the
# image at the exact relative paths sql/README.md's local reproduce
# steps already establish.
COPY sql/schema.sql sql/procs.sql sql/views.sql sql/monitoring_views.sql \
     sql/ingest_trades.sql sql/ingest_clearing.sql sql/ingest_confirms.sql \
     sql/load_lifecycle.sql sql/ingest_reconciliation.sql sql/ingest_root_cause.sql \
     sql/ingest_invoice.sql sql/ingest_aging.sql sql/ingest_audit_log.sql \
     sql/ingest_lineage.sql /usr/src/reconengine-init/sql/
COPY data/real/trades_real.csv /usr/src/reconengine-init/data/real/trades_real.csv
COPY data/synthetic/clearing_statements.csv data/synthetic/exchange_confirms.csv /usr/src/reconengine-init/data/synthetic/
COPY lifecycle/lifecycle_events.csv lifecycle/settlements.csv lifecycle/accounting_feed.csv /usr/src/reconengine-init/lifecycle/
COPY reconciliation/reconciliation_results.csv /usr/src/reconengine-init/reconciliation/
COPY root_cause/root_cause_labels.csv /usr/src/reconengine-init/root_cause/
COPY invoice_recon/invoice_reconciliation.csv /usr/src/reconengine-init/invoice_recon/
COPY aging/break_aging_daily.csv aging/break_aging_summary.csv /usr/src/reconengine-init/aging/
COPY audit_trail/audit_events.csv /usr/src/reconengine-init/audit_trail/
COPY lineage/lineage_events.csv /usr/src/reconengine-init/lineage/

USER mssql

ENTRYPOINT ["/entrypoint.sh"]
