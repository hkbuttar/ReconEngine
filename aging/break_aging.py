"""Multi-day rolling reconciliation with break aging and
escalation, over the real trades' actual date.

Real-data constraint, disclosed rather than worked around silently: the
real trade data (data/real/trades_real.csv) spans a single real calendar
day (a ~1-hour live-market pull). The plan calls for a genuine
multi-day rolling cycle, which real wall-clock time can't provide within
one session -- so this module simulates running the daily reconciliation
batch on a sequence of real, un-fabricated calendar dates *after* the
real trade date, checking each break's age and status as of each one.
This is the same disclosure pattern performance/ uses for
volume: a disclosed technique layered on real data, not fabricated trades
or fabricated dates -- every date here is a real calendar date, just used
as a simulated "as of" checkpoint rather than a date real trading
happened.

The one genuinely new synthetic element this step introduces: a
resolution date for each break (root_cause/root_cause_labels.csv's
non-CLEAN rows). No public source publishes real remediation timelines
either, for the same reason clearing/confirm discrepancies themselves are
synthetic (data/synthetic/README.md) -- disclosed distribution below.

Escalation tiers (disclosed judgment call): loosely adapted from SEC Reg
SHO Rule 204's real day-count escalation structure for fails-to-deliver
(T+1 initial close-out requirement; 5-consecutive-settlement-day
"threshold security" flag; 13-consecutive-settlement-day mandatory
close-out) -- a real regulatory precedent for why age-based escalation
tiers are a genuine industry pattern in this domain, not evidence that
these exact boundaries apply to reconciliation-break aging specifically
(a related but distinct concept from fails-to-deliver). ReconEngine's
tiers are an adapted illustration, not a citation-for-citation transplant.
"""

from __future__ import annotations

import csv
import datetime as dt
import pathlib
import random

REAL_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "real"
ROOT_CAUSE_DIR = pathlib.Path(__file__).resolve().parent.parent / "root_cause"
OUT_DIR = pathlib.Path(__file__).resolve().parent

RANDOM_SEED = 42
OBSERVATION_WINDOW_DAYS = 14

# Disclosed resolution-time distribution for non-CLEAN breaks.
RESOLUTION_BUCKETS = [
    (0.40, (0, 0)),    # resolved same day
    (0.30, (1, 2)),    # resolved within 1-2 days
    (0.20, (3, 7)),    # resolved within 3-7 days
    (0.10, None),      # never resolved within the observation window
]

ESCALATION_TIERS = [
    (0, 1, "TIER1_NORMAL"),
    (2, 5, "TIER2_ESCALATED"),
    (6, 13, "TIER3_MANAGEMENT"),
    (14, None, "TIER4_CRITICAL_AGED"),
]


def _read_csv(path: pathlib.Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def escalation_tier(age_days: int) -> str:
    for low, high, tier in ESCALATION_TIERS:
        if age_days >= low and (high is None or age_days <= high):
            return tier
    raise ValueError(f"no tier for age_days={age_days}")


def assign_resolution(origin_date: dt.date, rng: random.Random) -> dt.date | None:
    roll = rng.random()
    cumulative = 0.0
    for weight, offset_range in RESOLUTION_BUCKETS:
        cumulative += weight
        if roll < cumulative:
            if offset_range is None:
                return None
            offset = rng.randint(*offset_range)
            return origin_date + dt.timedelta(days=offset)
    return None


def build_aging_snapshots(breaks: list[dict], trade_dates: dict[str, dt.date], rng: random.Random) -> tuple[list[dict], list[dict]]:
    """Returns (daily_snapshots, break_summary). daily_snapshots has one
    row per (break, observation_date) while the break is still open --
    the rolling view. break_summary has one row per break with its final
    resolution outcome -- the aggregate view."""
    daily_snapshots = []
    break_summary = []

    for br in breaks:
        origin_date = trade_dates[br["trade_id_ref"]]
        resolved_date = assign_resolution(origin_date, rng)
        window_end = origin_date + dt.timedelta(days=OBSERVATION_WINDOW_DAYS)

        max_tier_reached = escalation_tier(0)
        for day_offset in range(OBSERVATION_WINDOW_DAYS + 1):
            observation_date = origin_date + dt.timedelta(days=day_offset)
            if resolved_date is not None and observation_date >= resolved_date:
                break  # resolved -- no longer open as of this or later observation dates
            age_days = (observation_date - origin_date).days
            tier = escalation_tier(age_days)
            max_tier_reached = tier
            daily_snapshots.append(
                {
                    "trade_id_ref": br["trade_id_ref"],
                    "stage": br["stage"],
                    "root_cause_category": br["root_cause_category"],
                    "origin_date": origin_date.isoformat(),
                    "observation_date": observation_date.isoformat(),
                    "age_days": age_days,
                    "escalation_tier": tier,
                }
            )

        break_summary.append(
            {
                "trade_id_ref": br["trade_id_ref"],
                "stage": br["stage"],
                "root_cause_category": br["root_cause_category"],
                "origin_date": origin_date.isoformat(),
                "resolved_date": resolved_date.isoformat() if resolved_date else "",
                "resolution_days": (resolved_date - origin_date).days if resolved_date else "",
                "still_open_at_window_end": resolved_date is None or resolved_date > window_end,
                "max_escalation_tier_reached": max_tier_reached,
            }
        )

    return daily_snapshots, break_summary


def _write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    trades = _read_csv(REAL_DIR / "trades_real.csv")
    trade_dates = {
        f"{t['venue']}:{t['native_trade_id']}": dt.datetime.fromisoformat(t["traded_at"].replace("Z", "+00:00")).date()
        for t in trades
    }

    labels = _read_csv(ROOT_CAUSE_DIR / "root_cause_labels.csv")
    breaks = [r for r in labels if r["root_cause_category"] != "CLEAN"]

    rng = random.Random(RANDOM_SEED)
    daily_snapshots, break_summary = build_aging_snapshots(breaks, trade_dates, rng)

    _write_csv(OUT_DIR / "break_aging_daily.csv", daily_snapshots)
    _write_csv(OUT_DIR / "break_aging_summary.csv", break_summary)

    from collections import Counter

    tier_counts_at_window_end = Counter(
        b["max_escalation_tier_reached"] for b in break_summary if b["still_open_at_window_end"]
    )
    resolution_bucket_counts = Counter(
        "unresolved" if b["resolution_days"] == "" else
        "same_day" if b["resolution_days"] == 0 else
        "1_2_days" if b["resolution_days"] in (1, 2) else
        "3_7_days"
        for b in break_summary
    )
    summary = {
        "total_breaks": len(breaks),
        "observation_window_days": OBSERVATION_WINDOW_DAYS,
        "resolution_outcome_counts": dict(resolution_bucket_counts),
        "still_open_at_window_end": sum(1 for b in break_summary if b["still_open_at_window_end"]),
        "tier_counts_among_still_open": dict(tier_counts_at_window_end),
        "daily_snapshot_rows": len(daily_snapshots),
    }
    import json

    (OUT_DIR / "generation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
