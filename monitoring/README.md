# monitoring/ — Monitoring, Observability & Alerting (Step 14)

## Metrics (`sql/monitoring_views.sql`)

Four views, computed live against the real-anchored dataset — these are
the canonical metric definitions Qlik (Step 15) and FastAPI (Step 18)
both consume, not redefined ad hoc in either place:

| view | metric |
|---|---|
| `vw_IngestionHealth` | success/failure rate, rows loaded/rejected per source (Step 4) |
| `vw_MatchRateByStage` | match/broken/missing rate per lifecycle stage (Step 5) |
| `vw_BreakAgingDistribution` | break count by escalation tier, open vs. resolved (Step 10) |
| `vw_InvoiceDiscrepancyRate` | discrepancy rate and net $ impact per venue (Step 9) |

Live result: ingestion 100% success (3/3 runs); match rate 90.95%
(clearing) / 91.55% (confirm); 254 breaks at `TIER4_CRITICAL_AGED`;
invoice discrepancy rate 6.25–7.36% across venues.

## Alerting (`alert_rules.py`)

Writes triggered alerts to the mutable `alerts` table (unlike
`audit_log`, alerts get acknowledged in real ops — an audit entry never
should, hence the different immutability treatment).

**Alerting thresholds are a deliberately higher bar than the
break/materiality thresholds that flag something as a break at all**
(Steps 9–10) — a disclosed distinction: materiality decides what counts
as broken; alerting decides what's urgent enough to page someone.
Conflating the two would either alert on everything (noise, since ~9-12%
of this project's data is broken by design) or miss the point of having
a break threshold at all.

| rule | threshold | severity | live result |
|---|---|---|---:|
| `CRITICAL_AGED_BREAK` | Step 10's real `TIER4_CRITICAL_AGED` (14+ days open) — reused, not reinvented | critical | 254 |
| `MATERIAL_INVOICE_DISCREPANCY` | \|delta\| > $10 **or** > 50% of expected fee — notably higher than Step 9's $0.01/10% "is it broken" bar | warning | 438 |
| `LOW_MATCH_RATE` | stage match rate < 85% — calibrated below this project's observed ~91% baseline, not an industry figure | critical | 0 (not currently breached) |
| `INGESTION_FAILURE` | any `ingestion_audit` row with `status='failed'` | critical | 0 (no ingestion has ever failed) |

The two zero-count rules are **left un-triggered**, not removed or
faked — a monitoring rule that's never fired is still a real, working
rule; manufacturing a failure to "prove" it works would defeat the
purpose of testing it against real project data. Spot-checked the
threshold logic directly: several `MATERIAL_INVOICE_DISCREPANCY` alerts
are for dollar amounts as small as $0.02–$3 — correct behavior, since
`double_billed` discrepancies are always exactly 100% over (well past the
50% relative bar) regardless of the trade's absolute size, exactly the
case the relative half of the threshold exists to catch.

## Run it

```bash
python3 monitoring/alert_rules.py   # requires reconengine-sql running
```

Idempotent by design: clears and re-inserts all alerts on each run
(monitoring state should reflect current reality, not accumulate stale
alerts from prior scans).
