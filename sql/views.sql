-- Views supporting the Qlik Sense data model. Kept as plain
-- presence/absence + raw-delta joins here; final break classification
-- (materiality tolerances, root-cause labels) is layered on top in
-- reconciliation/ and root_cause/, which will add their own
-- views once that logic exists.

CREATE OR ALTER VIEW vw_TradeReconciliationStatus AS
SELECT
    t.trade_id,
    t.venue,
    t.native_trade_id,
    t.symbol,
    t.side,
    t.price,
    t.quantity,
    t.traded_at,
    CASE WHEN c.clearing_id IS NULL THEN 'missing'
         WHEN c.reported_price <> t.price OR c.reported_quantity <> t.quantity OR c.reported_side <> t.side THEN 'broken'
         ELSE 'matched' END AS clearing_match_status,
    CASE WHEN x.confirm_id IS NULL THEN 'missing'
         WHEN x.reported_price <> t.price OR x.reported_quantity <> t.quantity OR x.reported_side <> t.side THEN 'broken'
         ELSE 'matched' END AS confirm_match_status,
    c.injected_break_type AS clearing_injected_break_type,
    x.injected_break_type AS confirm_injected_break_type
FROM trades t
LEFT JOIN clearing_statements c ON c.trade_id = t.trade_id
LEFT JOIN exchange_confirms x ON x.trade_id = t.trade_id;
GO

CREATE OR ALTER VIEW vw_LifecycleTimeline AS
SELECT
    e.trade_id,
    r.stage_code,
    r.stage_order,
    e.entered_at,
    e.expected_by,
    e.status
FROM lifecycle_events e
JOIN lifecycle_stage_ref r ON r.stage_code = e.stage_code;
GO

CREATE OR ALTER VIEW vw_SettlementStatus AS
SELECT
    s.trade_id,
    t.venue,
    t.symbol,
    s.expected_settle_date,
    s.actual_settle_date,
    s.settlement_status,
    DATEDIFF(day, s.expected_settle_date, s.actual_settle_date) AS days_late
FROM settlements s
JOIN trades t ON t.trade_id = s.trade_id;
GO

CREATE OR ALTER VIEW vw_DailyVolumeByVenue AS
SELECT
    venue,
    symbol,
    CAST(traded_at AS DATE) AS trade_date,
    COUNT(*) AS trade_count,
    SUM(quantity) AS total_quantity,
    SUM(price * quantity) AS total_notional
FROM trades
GROUP BY venue, symbol, CAST(traded_at AS DATE);
GO
