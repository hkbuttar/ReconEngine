"""Step 8 (query half): natural-language question -> T-SQL SELECT ->
execution against the live schema. The generated SQL is always shown
alongside the results, never executed silently -- this is a transparency
requirement, not a nicety: a wrong or misleading query should be
verifiable by inspection, not hidden behind a plain-English answer.

Safety: the model is instructed to emit exactly one read-only SELECT
statement, and the output is independently validated before execution
(must start with SELECT, must not contain any DDL/DML keyword) --
belt-and-suspenders, since prompt instructions alone aren't a security
boundary.
"""

from __future__ import annotations

import os
import re
import subprocess

import anthropic
from dotenv import load_dotenv

load_dotenv()

CONTAINER = "reconengine-sql"
SA_PASSWORD = "ReconEngine!2026"
SQLCMD = ["docker", "exec", CONTAINER, "/opt/mssql-tools18/bin/sqlcmd",
          "-S", "localhost", "-U", "sa", "-P", SA_PASSWORD, "-C", "-d", "reconengine"]

MODEL = "claude-sonnet-5"  # needs real reasoning over schema + question, not just templated synthesis

FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|EXEC|EXECUTE|TRUNCATE|MERGE|CREATE|GRANT|REVOKE|xp_|sp_)\b",
    re.IGNORECASE,
)

SCHEMA_DESCRIPTION = """
trades (trade_id PK, venue, native_trade_id, symbol, side, price, quantity, traded_at) -- real trades
clearing_statements (clearing_id PK, trade_id FK nullable, clearing_ref, reported_venue, reported_symbol,
    reported_side, reported_price, reported_quantity, statement_date, received_at, injected_break_type)
exchange_confirms (confirm_id PK, trade_id FK nullable, confirm_ref, reported_venue, reported_symbol,
    reported_side, reported_price, reported_quantity, confirm_timestamp, received_at, injected_break_type)
reconciliation_results (result_id PK, trade_id FK, stage ['clearing'|'confirm'], match_status
    ['matched'|'broken'|'missing'], price_diff_pct, quantity_diff_pct, side_match, injected_break_type)
root_cause_labels (label_id PK, trade_id FK, stage, root_cause_category
    ['CLEAN'|'TIMING'|'PRICING'|'QUANTITY'|'REFERENCE_DATA'|'MISSING_RECORD'|'ORPHAN_RECORD'|'CORPORATE_ACTION'],
    has_timing_issue, match_status, injected_break_type, lifecycle_status)
lifecycle_stage_ref (stage_code PK, stage_order, description)
lifecycle_events (event_id PK, trade_id FK, stage_code FK, entered_at, expected_by, status ['on_time'|'late'|'breached'])
settlements (settlement_id PK, trade_id FK, expected_settle_date, actual_settle_date, settlement_status, settlement_amount, currency)
accounting_feed (entry_id PK, trade_id FK, gl_account, debit_credit ['D'|'C'], amount, currency, posted_at, posting_status)
ingestion_audit (audit_id PK, source_name, source_file, started_at, completed_at, status, rows_read, rows_valid, rows_rejected, rows_loaded)
positions (position_id PK, venue, symbol, as_of_date, net_quantity, avg_price)
lineage_events (lineage_id PK, source_table, source_pk, target_table, target_pk, transform_step, is_synthetic_source)
"""

SYSTEM_PROMPT = f"""You translate a natural-language question about a post-trade reconciliation \
system into exactly one T-SQL SELECT statement against this SQL Server schema:

{SCHEMA_DESCRIPTION}

Rules:
- Output ONLY the SQL statement. No markdown fences, no explanation, no comments.
- Exactly one statement, must start with SELECT, must end with a semicolon.
- Never write INSERT/UPDATE/DELETE/DROP/ALTER/EXEC/CREATE or any other mutating statement.
- If the question cannot be answered from this schema, output exactly: NO_QUERY: <reason>
"""


def _extract_text(response: anthropic.types.Message) -> str:
    """Some models (e.g. extended-thinking Sonnet) prepend a ThinkingBlock
    before the TextBlock -- content[0] isn't reliably the answer."""
    for block in response.content:
        if block.type == "text":
            return block.text.strip()
    raise ValueError("no text block in response")


def _strip_markdown_fence(text: str) -> str:
    """The model is instructed not to wrap output in code fences but
    occasionally does anyway -- stripped here, BEFORE the safety check
    below, so is_safe_select() always validates the actual SQL rather
    than rejecting well-formed queries for a formatting artifact."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def nl_to_sql(question: str) -> str:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
    )
    return _strip_markdown_fence(_extract_text(response))


def is_safe_select(sql: str) -> bool:
    stripped = sql.strip()
    if not stripped.upper().startswith("SELECT"):
        return False
    if FORBIDDEN_KEYWORDS.search(stripped):
        return False
    if stripped.count(";") > 1:
        return False
    return True


def run_query(question: str) -> dict:
    sql = nl_to_sql(question)

    if sql.startswith("NO_QUERY:"):
        return {"question": question, "sql": None, "error": sql[len("NO_QUERY:"):].strip(), "rows": None}

    if not is_safe_select(sql):
        return {"question": question, "sql": sql, "error": "generated SQL failed the read-only safety check; not executed", "rows": None}

    result = subprocess.run(SQLCMD + ["-Q", f"SET NOCOUNT ON; {sql}"], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {"question": question, "sql": sql, "error": result.stderr or result.stdout, "rows": None}

    return {"question": question, "sql": sql, "error": None, "rows": result.stdout.strip()}


def main() -> None:
    import sys

    if len(sys.argv) < 2:
        print('usage: nl_query.py "<question>"')
        raise SystemExit(1)

    question = " ".join(sys.argv[1:])

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set -- cannot translate question to SQL.")
        raise SystemExit(1)

    result = run_query(question)
    print(f"Question: {result['question']}")
    print(f"Generated SQL: {result['sql']}")
    if result["error"]:
        print(f"Error: {result['error']}")
    else:
        print(f"Results:\n{result['rows']}")


if __name__ == "__main__":
    main()
