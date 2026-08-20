# llm_assist/ — LLM-Assisted Break Explanation & NL Query

Two modules, both live-tested against the real database and a real
Claude API key (`.env`, gitignored — never committed).

## `break_explainer.py` — plain-English explanations for ambiguous breaks

Explains two genuinely ambiguous cases this project actually has — not
synthetic breaks a rule already resolves cleanly:

1. **Fuzzy-match candidates** (`reconciliation/fuzzy_match_*.csv`) —
   an orphan record with more than one plausible real-trade match. 50 of
   110 clearing orphans have ≥2 candidates.
2. **"Timing breach, but on_time"** — a record genuinely late relative to
   normal processing, but still inside the looser T+1 settlement window.

Model: `claude-haiku-4-5-20251001` — cheap, sufficient for templated
synthesis over facts the prompt already provides in full. The system
prompt requires the model to use **only** the supplied facts, say so
explicitly when the data doesn't determine an answer, and end every
response with a fixed disclosure sentence — verified live, not just
instructed:

```
$ python3 llm_assist/break_explainer.py fuzzy CLEARING-ORPHAN-000000 clearing

A clearing orphan record (BTC-USD buy of 0.00000002 at $69,521.66) has been
flagged as synthetic and matched against two candidate trades from Coinbase
with identical quantity and side, but both candidates show lower prices
($68,707.08 and $68,640.73) occurring 17–19 minutes earlier. The price
variance (approximately 1.2–1.3% difference) falls within the fuzzy-match
tolerance of 5%, though the orphan's reported price is noticeably higher
than both candidates, and the data does not definitively establish which
candidate (if either) represents the actual underlying trade. A human
review is required to determine whether this orphan should be matched to
one of the candidates, reconciled as a separate transaction, or
investigated further for data quality issues.

This is an AI-generated explanation for triage only; verify against the
source records before acting on it.
```

## `nl_query.py` — natural-language question → SQL → live results

Model: `claude-sonnet-5` — needs real reasoning over the schema and
question, not just templated synthesis (a cheaper model would be more
error-prone here). The generated SQL is **always shown**, never executed
silently.

**Safety, two independent layers**: (1) the system prompt requires
exactly one read-only `SELECT`, refuses to generate anything else and
says why; (2) `is_safe_select()` independently re-validates — must start
with `SELECT`, must not contain any DDL/DML keyword, at most one
statement — a backstop in case the model's own refusal ever fails, not a
redundant nicety. Both layers verified live:

```
$ python3 llm_assist/nl_query.py "How many trades had a quantity mismatch at the clearing stage?"
Generated SQL: SELECT COUNT(*) AS trade_count FROM reconciliation_results
    WHERE stage = 'clearing' AND quantity_diff_pct IS NOT NULL AND quantity_diff_pct <> 0;
Results: trade_count = 348   # matches root_cause_labels' QUANTITY/clearing count exactly

$ python3 llm_assist/nl_query.py "Delete all trades from the kraken venue"
Error: The request is a mutating (DELETE) operation, which is not
permitted; only SELECT statements can be generated.   # model's own refusal, layer 1

$ python3 -c "from nl_query import is_safe_select; \
    print(is_safe_select('SELECT * FROM trades; DROP TABLE trades;'))"
False   # layer 2, tested directly, bypassing the model entirely
```

**Bug found and fixed during live testing**: the model occasionally
wraps its SQL in ` ```sql ` fences despite an explicit instruction not
to — this made a *correct, safe* query fail the "starts with SELECT"
check for the wrong reason (formatting, not safety). Fixed by stripping
fences *before* validation (`_strip_markdown_fence()`), not by loosening
the check.

## Environment

Requires `ANTHROPIC_API_KEY` in `.env` (repo root, gitignored — see
`.env.example`) and the `reconengine-sql` container running for
`nl_query.py`. Both scripts print a clear message and exit rather than
failing obscurely if the key is missing.
