-- load: lineage_events (lineage/build_lineage.py output) --
-- table-level edges, 18 rows. source_pk/target_pk are 0 (sentinel for
-- "table-level, not row-level" -- see lineage/build_lineage.py's
-- docstring). Small, static graph -- reloaded fresh each run rather than
-- anti-joined.

DELETE FROM lineage_events;
GO

CREATE TABLE #stg_lineage (
    source_table NVARCHAR(60), source_pk NVARCHAR(10), target_table NVARCHAR(60),
    target_pk NVARCHAR(10), transform_step NVARCHAR(100), is_synthetic_source NVARCHAR(10)
);
GO

BULK INSERT #stg_lineage FROM '/tmp/lineage_events.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

INSERT INTO lineage_events (source_table, source_pk, target_table, target_pk, transform_step, is_synthetic_source)
SELECT source_table, CAST(source_pk AS BIGINT), target_table, CAST(target_pk AS BIGINT), transform_step,
       CASE WHEN is_synthetic_source = 'True' THEN 1 ELSE 0 END
FROM #stg_lineage;
GO
