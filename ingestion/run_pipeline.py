"""ETL orchestrator: validates each source CSV (schema, types,
duplicate keys, referential integrity) before loading, loads it via its
sql/ingest_*.sql script, and logs every run to the `ingestion_audit`
table -- feeding lineage and monitoring: ingestion
success/failure rate.

No local ODBC driver/pyodbc is set up in this environment (see
sql/README.md) -- all DB access here goes through `docker exec
reconengine-sql sqlcmd`, the same mechanism used to validate the schema
earlier. This is a dev-environment constraint, not a design choice;
a production version would connect directly.

Three sources, run in dependency order (clearing/confirm reference
trades):
  1. trades           <- data/real/trades_real.csv (front-office/exchange)
  2. clearing_statements <- data/synthetic/clearing_statements.csv (clearing firm)
  3. exchange_confirms   <- data/synthetic/exchange_confirms.csv (exchange)

Validation is deliberately Python-side and pre-load, not left to the
database to reject: a source that fails validation should never reach
BULK INSERT, and the reason should be visible in the audit row without
having to parse a SQL error. Rows that fail validation are excluded from
the load and counted as `rows_rejected`; the run still proceeds with the
valid rows rather than failing the whole batch on one bad row -- matching
how a real ETL pipeline would triage a partially-dirty source file.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_REAL = REPO_ROOT / "data" / "real"
DATA_SYNTHETIC = REPO_ROOT / "data" / "synthetic"
SQL_DIR = REPO_ROOT / "sql"

CONTAINER = "reconengine-sql"
SA_PASSWORD = "ReconEngine!2026"
SQLCMD = ["docker", "exec", CONTAINER, "/opt/mssql-tools18/bin/sqlcmd",
          "-S", "localhost", "-U", "sa", "-P", SA_PASSWORD, "-C", "-d", "reconengine"]


def _sql_escape(value: str) -> str:
    return value.replace("'", "''")


def run_sqlcmd_query(query: str) -> str:
    result = subprocess.run(SQLCMD + ["-Q", query], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"sqlcmd query failed: {result.stdout}\n{result.stderr}")
    return result.stdout


def run_sqlcmd_file(container_path: str) -> str:
    result = subprocess.run(SQLCMD + ["-i", container_path], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"sqlcmd file {container_path} failed: {result.stdout}\n{result.stderr}")
    return result.stdout


def sql_scalar(query: str) -> int:
    out = subprocess.run(
        SQLCMD + ["-h", "-1", "-W", "-Q", f"SET NOCOUNT ON; {query}"],
        capture_output=True, text=True, timeout=30,
    )
    lines = [line.strip() for line in out.stdout.splitlines() if line.strip() and not line.strip().startswith("(")]
    return int(lines[0]) if lines else 0


def docker_cp(local_path: pathlib.Path, container_dest: str) -> None:
    subprocess.run(["docker", "cp", str(local_path), f"{CONTAINER}:{container_dest}"], check=True, capture_output=True)


# --- Validation ---------------------------------------------------------

REQUIRED_TRADE_COLS = {"venue", "native_trade_id", "symbol", "side", "price", "quantity", "traded_at"}
REQUIRED_SYNTHETIC_COLS = {
    "trade_id_ref", "reported_venue", "reported_symbol", "reported_side",
    "reported_price", "reported_quantity", "received_at", "injected_break_type",
}


def _parse_positive_float(value: str) -> float | None:
    try:
        f = float(value)
    except ValueError:
        return None
    return f if f > 0 else None


def _parse_ts(value: str) -> bool:
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_trades(rows: list[dict]) -> tuple[list[dict], list[tuple[dict, str]], dict]:
    valid, rejected = [], []
    seen_keys: set[tuple[str, str]] = set()
    for row in rows:
        if not REQUIRED_TRADE_COLS.issubset(row.keys()):
            rejected.append((row, "missing required column"))
            continue
        key = (row["venue"], row["native_trade_id"])
        if key in seen_keys:
            rejected.append((row, "duplicate (venue, native_trade_id) within source file"))
            continue
        if row["side"] not in ("buy", "sell"):
            rejected.append((row, f"invalid side '{row['side']}'"))
            continue
        if _parse_positive_float(row["price"]) is None or _parse_positive_float(row["quantity"]) is None:
            rejected.append((row, "non-positive or non-numeric price/quantity"))
            continue
        if not _parse_ts(row["traded_at"]):
            rejected.append((row, "unparseable traded_at"))
            continue
        seen_keys.add(key)
        valid.append(row)
    summary = {"duplicate_keys_in_file": sum(1 for _, r in rejected if "duplicate" in r)}
    return valid, rejected, summary


def validate_synthetic(rows: list[dict], real_trade_keys: set[tuple[str, str]], ref_col: str) -> tuple[list[dict], list[tuple[dict, str]], dict]:
    valid, rejected = [], []
    seen_refs: set[str] = set()
    dangling_refs = 0
    for row in rows:
        if not (REQUIRED_SYNTHETIC_COLS | {ref_col}).issubset(row.keys()):
            rejected.append((row, "missing required column"))
            continue
        ref_value = row[ref_col]
        if ref_value in seen_refs:
            rejected.append((row, f"duplicate {ref_col} within source file"))
            continue
        if row["reported_side"] not in ("buy", "sell"):
            rejected.append((row, f"invalid reported_side '{row['reported_side']}'"))
            continue
        if _parse_positive_float(row["reported_price"]) is None or _parse_positive_float(row["reported_quantity"]) is None:
            rejected.append((row, "non-positive or non-numeric reported_price/reported_quantity"))
            continue
        if not _parse_ts(row["received_at"]):
            rejected.append((row, "unparseable received_at"))
            continue
        # Referential check: a non-empty trade_id_ref must resolve to a
        # real trade. An empty ref is a disclosed, expected `orphan` break
        # (data/synthetic/README.md) -- not a data quality problem.
        ref = row["trade_id_ref"]
        if ref and ":" in ref:
            venue, native_id = ref.split(":", 1)
            if (venue, native_id) not in real_trade_keys:
                dangling_refs += 1
                rejected.append((row, f"trade_id_ref '{ref}' does not resolve to any real trade"))
                continue
        seen_refs.add(ref_value)
        valid.append(row)
    summary = {"dangling_trade_refs": dangling_refs}
    return valid, rejected, summary


def _write_valid_csv(path: pathlib.Path, valid_rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(valid_rows)


# --- Orchestration -------------------------------------------------------

def ingest_source(
    source_name: str,
    csv_path: pathlib.Path,
    container_csv_name: str,
    ingest_sql_file: str,
    target_table: str,
    validate_fn,
) -> dict:
    started_at = dt.datetime.now(tz=dt.timezone.utc)
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys()) if rows else []

    valid_rows, rejected_rows, quality_summary = validate_fn(rows)
    quality_summary["rows_read"] = len(rows)
    quality_summary["rows_valid"] = len(valid_rows)
    quality_summary["rows_rejected"] = len(rejected_rows)

    audit_id = _log_audit_start(source_name, str(csv_path.relative_to(REPO_ROOT)), started_at, len(rows), len(valid_rows), len(rejected_rows), quality_summary)

    try:
        before_count = sql_scalar(f"SELECT COUNT(*) FROM {target_table};")

        # Write only the valid rows to /tmp for BULK INSERT, so a rejected
        # row can never reach the database even as a NULL-y placeholder.
        clean_path = REPO_ROOT / "ingestion" / f"_clean_{container_csv_name}"
        _write_valid_csv(clean_path, valid_rows, fieldnames)
        docker_cp(clean_path, f"/tmp/{container_csv_name}")
        clean_path.unlink()

        docker_cp(SQL_DIR / ingest_sql_file, f"/tmp/{ingest_sql_file}")
        run_sqlcmd_file(f"/tmp/{ingest_sql_file}")

        after_count = sql_scalar(f"SELECT COUNT(*) FROM {target_table};")
        rows_loaded = after_count - before_count

        _log_audit_complete(audit_id, "succeeded", rows_loaded=rows_loaded)
        status = "succeeded"
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: any failure must still be audited
        _log_audit_complete(audit_id, "failed", rows_loaded=0, error_message=str(exc))
        status = "failed"
        rows_loaded = 0

    return {
        "source": source_name,
        "status": status,
        "rows_read": len(rows),
        "rows_valid": len(valid_rows),
        "rows_rejected": len(rejected_rows),
        "rows_loaded": rows_loaded,
        "sample_rejections": [reason for _, reason in rejected_rows[:5]],
    }


def _log_audit_start(source_name, source_file, started_at, rows_read, rows_valid, rows_rejected, quality_summary) -> int:
    summary_json = _sql_escape(json.dumps(quality_summary))
    query = f"""
    SET NOCOUNT ON;
    INSERT INTO ingestion_audit (source_name, source_file, started_at, status, rows_read, rows_valid, rows_rejected, quality_check_summary)
    VALUES ('{_sql_escape(source_name)}', '{_sql_escape(source_file)}', '{started_at.isoformat()}', 'running', {rows_read}, {rows_valid}, {rows_rejected}, '{summary_json}');
    SELECT SCOPE_IDENTITY();
    """
    out = subprocess.run(SQLCMD + ["-h", "-1", "-W", "-Q", query], capture_output=True, text=True, timeout=30)
    lines = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    return int(float(lines[0])) if lines else -1


def _log_audit_complete(audit_id: int, status: str, rows_loaded: int, error_message: str | None = None) -> None:
    error_clause = f"'{_sql_escape(error_message)}'" if error_message else "NULL"
    query = (
        f"UPDATE ingestion_audit SET status = '{status}', rows_loaded = {rows_loaded}, "
        f"completed_at = SYSUTCDATETIME(), error_message = {error_clause} WHERE audit_id = {audit_id};"
    )
    run_sqlcmd_query(query)


def main() -> None:
    with (DATA_REAL / "trades_real.csv").open() as f:
        real_trade_keys = {(r["venue"], r["native_trade_id"]) for r in csv.DictReader(f)}

    results = []
    results.append(
        ingest_source(
            "trades", DATA_REAL / "trades_real.csv", "trades_real.csv",
            "ingest_trades.sql", "trades", validate_trades,
        )
    )
    results.append(
        ingest_source(
            "clearing_statements", DATA_SYNTHETIC / "clearing_statements.csv", "clearing_statements.csv",
            "ingest_clearing.sql", "clearing_statements",
            lambda rows: validate_synthetic(rows, real_trade_keys, "clearing_ref"),
        )
    )
    results.append(
        ingest_source(
            "exchange_confirms", DATA_SYNTHETIC / "exchange_confirms.csv", "exchange_confirms.csv",
            "ingest_confirms.sql", "exchange_confirms",
            lambda rows: validate_synthetic(rows, real_trade_keys, "confirm_ref"),
        )
    )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
