 load: audit_log (audit_trail/build_audit_log.py output). Same
-- temp-table + BULK INSERT pattern as sql/ingest_*.sql, but loads into a
-- LEDGER table -- staged through a plain temp table first rather than
-- BULK INSERT directly into the ledger table, sidestepping any
-- ledger-specific bulk-load restrictions rather than discovering one
-- mid-load. No idempotent anti-join here: an append-only ledger table is
-- an audit trail, not a queryable-and-correctable dataset -- rerunning
-- this script is expected to append a second full history, not update
-- one, consistent with what "append-only" means.

CREATE TABLE #stg_audit (
    event_type NVARCHAR(40), entity_type NVARCHAR(40), entity_ref NVARCHAR(60),
    event_at NVARCHAR(50), details NVARCHAR(500)
);
GO

BULK INSERT #stg_audit FROM '/tmp/audit_events.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

INSERT INTO audit_log (event_type, entity_type, entity_ref, event_at, details)
SELECT event_type, entity_type, entity_ref, CAST(CONVERT(DATETIMEOFFSET, event_at, 127) AS DATETIME2), details
FROM #stg_audit;
GO
