-- Common reconciliation stored procedures. Full break
-- classification logic (matching tolerances, root-cause taxonomy) belongs
-- to reconciliation/ and root_cause/ -- these procs expose the
-- raw joins/aggregates those steps and Qlik build on, not final verdicts.

CREATE OR ALTER PROCEDURE usp_GetTradeLifecycleStatus
    @trade_id BIGINT
AS
BEGIN
    SET NOCOUNT ON;
    SELECT r.stage_code, r.stage_order, e.entered_at, e.expected_by, e.status
    FROM lifecycle_stage_ref r
    LEFT JOIN lifecycle_events e
        ON e.stage_code = r.stage_code AND e.trade_id = @trade_id
    ORDER BY r.stage_order;
END;
GO

-- Real trades with no matching clearing_statement row at all (a "missing"
-- clearing break) plus orphan clearing_statement rows with no matching
-- real trade (the clearing firm reported something the front office never
-- captured).
CREATE OR ALTER PROCEDURE usp_GetUnmatchedClearingRecords
AS
BEGIN
    SET NOCOUNT ON;
    SELECT t.trade_id, t.venue, t.native_trade_id, t.symbol, t.traded_at,
           'missing_clearing' AS break_type
    FROM trades t
    LEFT JOIN clearing_statements c ON c.trade_id = t.trade_id
    WHERE c.clearing_id IS NULL

    UNION ALL

    SELECT NULL AS trade_id, c.reported_venue AS venue, NULL AS native_trade_id,
           c.reported_symbol AS symbol, c.received_at AS traded_at,
           'orphan_clearing' AS break_type
    FROM clearing_statements c
    WHERE c.trade_id IS NULL;
END;
GO

-- Same pattern for exchange_confirms.
CREATE OR ALTER PROCEDURE usp_GetUnmatchedConfirmRecords
AS
BEGIN
    SET NOCOUNT ON;
    SELECT t.trade_id, t.venue, t.native_trade_id, t.symbol, t.traded_at,
           'missing_confirm' AS break_type
    FROM trades t
    LEFT JOIN exchange_confirms x ON x.trade_id = t.trade_id
    WHERE x.confirm_id IS NULL

    UNION ALL

    SELECT NULL AS trade_id, x.reported_venue AS venue, NULL AS native_trade_id,
           x.reported_symbol AS symbol, x.received_at AS traded_at,
           'orphan_confirm' AS break_type
    FROM exchange_confirms x
    WHERE x.trade_id IS NULL;
END;
GO

-- Trades where the clearing statement or exchange confirm's reported
-- price/quantity/side differs from the real trade record -- raw deltas
-- only, no tolerance/materiality judgment applied here (see
-- reconciliation/ for that).
CREATE OR ALTER PROCEDURE usp_GetFieldMismatches
AS
BEGIN
    SET NOCOUNT ON;
    SELECT t.trade_id, t.venue, t.native_trade_id, 'clearing' AS source,
           t.price AS real_price, c.reported_price,
           t.quantity AS real_quantity, c.reported_quantity,
           t.side AS real_side, c.reported_side,
           c.injected_break_type
    FROM trades t
    JOIN clearing_statements c ON c.trade_id = t.trade_id
    WHERE c.reported_price <> t.price
       OR c.reported_quantity <> t.quantity
       OR c.reported_side <> t.side

    UNION ALL

    SELECT t.trade_id, t.venue, t.native_trade_id, 'confirm' AS source,
           t.price AS real_price, x.reported_price,
           t.quantity AS real_quantity, x.reported_quantity,
           t.side AS real_side, x.reported_side,
           x.injected_break_type
    FROM trades t
    JOIN exchange_confirms x ON x.trade_id = t.trade_id
    WHERE x.reported_price <> t.price
       OR x.reported_quantity <> t.quantity
       OR x.reported_side <> t.side;
END;
GO

-- Rebuilds the positions table from trades for a given venue/symbol/date
-- (idempotent: replaces the row rather than accumulating duplicates).
CREATE OR ALTER PROCEDURE usp_RecomputePosition
    @venue NVARCHAR(20),
    @symbol NVARCHAR(20),
    @as_of_date DATE
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @net_qty DECIMAL(18,8), @avg_price DECIMAL(18,8);

    SELECT
        @net_qty = SUM(CASE WHEN side = 'buy' THEN quantity ELSE -quantity END),
        @avg_price = SUM(price * quantity) / NULLIF(SUM(quantity), 0)
    FROM trades
    WHERE venue = @venue AND symbol = @symbol
      AND CAST(traded_at AS DATE) <= @as_of_date;

    MERGE positions AS target
    USING (SELECT @venue AS venue, @symbol AS symbol, @as_of_date AS as_of_date) AS src
        ON target.venue = src.venue AND target.symbol = src.symbol AND target.as_of_date = src.as_of_date
    WHEN MATCHED THEN
        UPDATE SET net_quantity = ISNULL(@net_qty, 0), avg_price = ISNULL(@avg_price, 0), updated_at = SYSUTCDATETIME()
    WHEN NOT MATCHED THEN
        INSERT (venue, symbol, as_of_date, net_quantity, avg_price)
        VALUES (@venue, @symbol, @as_of_date, ISNULL(@net_qty, 0), ISNULL(@avg_price, 0));
END;
GO
