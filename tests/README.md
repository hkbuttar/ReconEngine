# tests/ — Testing & Validation

70 tests, all passing, covering every category the plan calls for:
matching engine correctness, state machine transitions, root-cause
classifier sanity, SQL Server schema constraints, audit trail
immutability, invoice reconciliation matching, lineage completeness, and
a performance regression baseline.

## Structure

**Pure unit tests** (no Docker/DB needed, run anywhere):

| file | tests | covers |
|---|---:|---|
| `test_matching_engine.py` | 16 | tolerance boundaries, missing/broken/matched classification, fuzzy-match candidate search |
| `test_lifecycle_state_machine.py` | 12 | on_time/late/breached boundaries, business-day math, the gating rule, the monotonicity guard |
| `test_taxonomy.py` | 13 | crosswalk priority order, every category has a real citation |
| `test_invoice_reconciliation.py` | 6 | the combined absolute+relative materiality rule — specifically re-tests the exact bug found and fixed (`invoice_recon/README.md`), pinning the fix down against regression |
| `test_performance_regression.py` | 2 | throughput vs. the recorded baseline (452,610 trades/sec), self-contained in-memory benchmark, 20%-of-baseline threshold to avoid flaky failures from ordinary machine-load variance |

**DB-dependent tests** (`tests/conftest.py` skips these gracefully, not a
hard failure, if `reconengine-sql` isn't reachable):

| file | tests | covers |
|---|---:|---|
| `test_schema_constraints.py` | 8 | every UNIQUE/CHECK/FOREIGN KEY constraint is actually enforced by the live engine, not just declared in `sql/schema.sql` |
| `test_audit_trail_immutability.py` | 6 | `UPDATE`/`DELETE` against `audit_log` both fail with error 37359; a normal table doesn't share the restriction; `sys.tables.ledger_type` confirms it's real engine-level enforcement |
| `test_lineage_completeness.py` | 7 | the lineage graph has no orphan nodes, no cycles, every table traces back to the real trades; the live `lineage_events` table matches the code-defined graph exactly |

## Bugs found while writing these tests (disclosed, not swept under the rug)

- **`sqlcmd`'s exit code is 0 even on a SQL error** — the schema
  constraint tests originally asserted on `returncode != 0`, which failed
  even though the constraints were genuinely being enforced (real "Msg
  2627"/"Msg 547" errors in `stdout`). Fixed by checking for the error
  message content instead — a real gotcha about `sqlcmd`'s behavior, not
  a schema bug.
- **A test fixture reused a real trade_id already carrying both stages**,
  so the intended CHECK-constraint test tripped the UNIQUE constraint
  instead. Fixed by inserting an isolated, cleaned-up throwaway trade
  first.
- **`sys.tables.ledger_type` is `3` (`APPEND_ONLY_LEDGER_TABLE`), not `2`**
  as initially assumed from memory — caught immediately by running the
  test against the real catalog view rather than trusting the assumption,
  consistent with this project's citation/verification discipline
  throughout.

## Run it

```bash
python3 -m pytest tests/ -v          # full suite
python3 -m pytest tests/test_matching_engine.py -v   # unit tests only, no Docker needed
```
