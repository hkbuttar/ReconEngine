-- Per-source load: trades (front-office/exchange source). Uses a
-- local temp table (#-prefixed), not a permanent staging table like
-- sql/load_data.sql -- session-scoped, so a failed run can't
-- leave a dangling table behind the way earlier debugging did.
-- Idempotent: anti-joins against existing trades on the natural key, so
-- rerunning against a source that's already (partly) loaded only inserts
-- what's new instead of violating the unique constraint or duplicating rows.

CREATE TABLE #stg_trades (
    venue NVARCHAR(20), native_trade_id NVARCHAR(40), agg_trade_id NVARCHAR(40), symbol NVARCHAR(20),
    side NVARCHAR(4), price NVARCHAR(40), quantity NVARCHAR(40), traded_at NVARCHAR(50)
);
GO

BULK INSERT #stg_trades FROM '/tmp/trades_real.csv'
    WITH (FORMAT='CSV', FIRSTROW=2, FIELDQUOTE='"', FIELDTERMINATOR=',', ROWTERMINATOR='0x0d0a');
GO

INSERT INTO trades (venue, native_trade_id, symbol, side, price, quantity, traded_at)
SELECT s.venue, s.native_trade_id, s.symbol, s.side, CAST(s.price AS DECIMAL(18,8)), CAST(s.quantity AS DECIMAL(18,8)),
       CAST(CONVERT(DATETIMEOFFSET, s.traded_at, 127) AS DATETIME2)
FROM #stg_trades s
WHERE NOT EXISTS (
    SELECT 1 FROM trades t WHERE t.venue = s.venue AND t.native_trade_id = s.native_trade_id
);
GO
