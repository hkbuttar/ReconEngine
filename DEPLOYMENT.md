# Deployment

Three independent pieces: SQL Server, the Qlik dashboard, and the FastAPI
backend. Each documented below with what's actually verified vs. what
needs your own account/credentials.

## SQL Server

Three real hosting options, in order of how this project actually used
them:

1. **Local Docker** (what every other step in this project runs
   against) — `sql/README.md` has the full reproduce steps.
   `mcr.microsoft.com/mssql/server:2022-latest`, dev/throwaway, not
   durable.
2. **SQL Server Express**, locally, no Docker — same image family, free,
   but a real install (not scripted here; Microsoft's own installer).
3. **Render private service** (`sql/deploy/`) — the real path this
   project deploys with. Render has no managed SQL Server offering, so
   instead of reaching out to a separate cloud provider (e.g. Azure SQL),
   SQL Server runs as a second Docker-based service on the same Render
   account, declared as `type: pserv` in `render.yaml` alongside the
   backend web service — private (no public URL, reachable only from
   other services in the same Blueprint), with a persistent disk mounted
   at `/var/opt/mssql` so data survives restarts.

### The self-initializing deploy image (`sql/deploy/`)

`sql/deploy/Dockerfile` + `sql/deploy/entrypoint.sh` build a SQL Server
image that provisions itself on first boot — no manual `sqlcmd` session
required afterward. `entrypoint.sh` starts the engine, waits for it to
accept connections, then checks whether the `reconengine` database
already exists:

- **First boot**: creates the database, loads `schema.sql` → `procs.sql`
  → `views.sql` → `monitoring_views.sql`, then the full real + synthetic
  data load in the same order `sql/README.md` documents for local dev
  (`ingest_trades.sql` through `ingest_lineage.sql`).
- **Every later restart** (persistent disk keeps the data directory): the
  `reconengine` database already exists, so the whole init block is
  skipped and SQL Server just starts normally.

**Verified locally, end to end**, built and run as a standalone
container (not just read as a Dockerfile):

```bash
docker build -f sql/deploy/Dockerfile -t reconengine-sql-deploy .
docker run -d --name reconengine-sql-deploy-test \
  -e ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD='ReconEngine!2026' \
  -p 1434:1433 reconengine-sql-deploy
```

Row counts after first-boot init matched the project's known-correct
baseline exactly — `trades` 11,008, `clearing_statements` 10,891,
`exchange_confirms` 10,911, `lifecycle_events` 53,971,
`reconciliation_results` 22,016, `root_cause_labels` 22,016,
`invoice_reconciliation` 11,008, `break_aging_daily` 7,579, `audit_log`
5,746, `lineage_events` 18.

**A real bug found and fixed here**: `sqlcmd`'s exit code is always `0`,
even when a script fails outright (documented previously in
`tests/README.md`) — so `entrypoint.sh`'s `set -e` and its final
"database initialized" log line don't actually prove the load succeeded.
Row-count verification against known baselines (above), not the log
message, is what confirms this works — the same discipline used
throughout this project's "verified vs. claimed" distinction. That
verification caught a real corruption bug: an earlier repo-wide cleanup
pass (stripping leftover "Step N" references) used a regex whose greedy
leading `\s*` ate the newline before some `-- ` comments, fusing a SQL
statement terminator directly onto the next comment's text with zero
whitespace (e.g. `...match_status);: industry-grounded root-cause
labels...`) — invalid syntax that broke `schema.sql` silently under
`sqlcmd`'s always-0 exit code. Fixed by restoring the missing newline and
`-- ` prefix at all 7 affected lines (confirmed via targeted grep that no
other file in the repo has the same corruption signature).

**Not yet verified**: an actual Render deploy of this service (needs
your Render account, same reasoning as everything else in this project
that stops at "needs your account") — verified locally against a real
standalone container instead, which is the same image `render.yaml`
builds.

Azure SQL (or any other reachable SQL Server) still works as a drop-in
alternative if preferred — same schema/load sequence, just point
`RECONENGINE_ODBC_CONNECTION_STRING` at it instead:
`sqlcmd -S <server>.database.windows.net -d reconengine -U <user> -i sql/schema.sql`
(repeat for `procs.sql`, `views.sql`, `monitoring_views.sql`, then the
`ingest_*.sql`/data load sequence in `sql/README.md`).

## Qlik dashboard

Covered already — `qlik/README.md`. Qlik Cloud, set up interactively;
not something scriptable from here.

## FastAPI backend

`backend/main.py`, dual-mode DB access (`backend/db_client.py`): a real
`pyodbc` connection when `RECONENGINE_ODBC_CONNECTION_STRING` is set, the
local `docker exec reconengine-sql sqlcmd` mechanism otherwise (dev-only).

### What was actually verified here, and how

Installing Microsoft's ODBC driver directly on this machine (macOS) hit a
real wall: it requires updating Xcode Command Line Tools, a sudo-gated
system change with a large download, not worth pushing through right
after this project's own disk-space incident (`README.md`'s Results
section). But that's a macOS-specific problem — inside the Linux
container `Dockerfile` builds, installing the same driver is a plain
`apt-get`. So rather than leave the pyodbc path untested, the actual
deploy image was built and run locally, end to end:

```bash
docker build -t reconengine-backend .

# Pointed at the real reconengine-sql container over Docker's bridge
# network (172.17.0.3 here -- `docker inspect reconengine-sql --format
# '{{.NetworkSettings.IPAddress}}'` to find yours):
docker run -d --name reconengine-backend-test -p 8001:8000 \
  -e "RECONENGINE_ODBC_CONNECTION_STRING=DRIVER={ODBC Driver 18 for SQL Server};SERVER=172.17.0.3,1433;DATABASE=reconengine;UID=sa;PWD=ReconEngine!2026;TrustServerCertificate=yes;" \
  reconengine-backend

curl http://localhost:8001/health                    # -> {"status":"ok"}
curl http://localhost:8001/monitoring/match-rate      # -> real 90.95%/91.55%, identical to the sqlcmd path
curl http://localhost:8001/monitoring/alerts | jq length   # -> 692, identical to the sqlcmd path
```

Both the image build and a real `pyodbc` connection through it were
confirmed working, returning the same real numbers as every other
verification in this project — this is the path `render.yaml` actually
runs, not an untested one.

**One real difference found between the two modes, disclosed rather than
papered over**: `pyodbc` returns typed values (`"matched": 10012` as a
JSON integer); the `sqlcmd`-parsing fallback returns everything as
strings (`"matched": "10012"`). Both are correct, neither silently wrong,
but a strict API consumer comparing byte-for-byte output between local
dev and production would notice the difference.

**One real robustness gap found and fixed**: running the image with
*neither* `RECONENGINE_ODBC_CONNECTION_STRING` set *nor* `docker`
available (exactly the deployed-without-configuration case) originally
produced an opaque generic 500 — `docker` genuinely isn't on `PATH`
inside the container, and that `FileNotFoundError` wasn't caught.
Fixed in `backend/db_client.py` to raise a clear, actionable error
instead (verified: `{"detail":"database query failed: no database
connection available: RECONENGINE_ODBC_CONNECTION_STRING is not set..."}`).

**A second real bug found and fixed while writing the `Dockerfile`
itself**: `python:3.11-slim` now resolves to Debian 13 (trixie), whose
stricter SHA-1 signing policy rejects Microsoft's Debian-12-targeted apt
repo key — the build failed outright on the first attempt. Fixed by
pinning `python:3.11-slim-bookworm` explicitly rather than the floating
tag.

**Not verified here**: an actual `render.yaml` deploy (needs your GitHub
repo connected + your Render account — same reasoning as everything else
in this project that stops at "needs your account") and a real Azure SQL
connection specifically (verified against the local container instead,
over the same `pyodbc` code path — the connection string is the only
thing that would change).

### Deploy to Render

1. Push this repo to GitHub (Render's Blueprint deploy reads from a
   connected git repo).
2. In the Render dashboard: **New +** → **Blueprint**, point it at the
   repo. Render reads `render.yaml` and creates both services:
   `reconengine-sql-db` (private, `type: pserv`, persistent disk) and
   `reconengine-backend` (public web service).
3. Set `MSSQL_SA_PASSWORD` on `reconengine-sql-db` in the Render
   dashboard (`sync: false`, not committed) — `ACCEPT_EULA` is already
   set in `render.yaml`.
4. Set `RECONENGINE_ODBC_CONNECTION_STRING` and `ANTHROPIC_API_KEY` on
   `reconengine-backend`. The connection string points at the SQL
   service's internal hostname (Render's private-service DNS naming —
   confirm the exact host in the dashboard once `reconengine-sql-db` is
   provisioned) and must use the *same* password set in step 3, e.g.:
   `DRIVER={ODBC Driver 18 for SQL Server};SERVER=reconengine-sql-db:1433;DATABASE=reconengine;UID=sa;PWD=<same password as MSSQL_SA_PASSWORD>;TrustServerCertificate=yes;`
   The port must be `1433`, not whatever generic port the dashboard shows
   by default — `render.yaml` sets `PORT=1433` on `reconengine-sql-db`
   specifically because the official SQL Server image doesn't declare an
   `EXPOSE`, so without that override Render falls back to its generic
   `10000` default, which nothing inside the container is listening on.
5. First boot of `reconengine-sql-db` runs the full init sequence (schema
   + real/synthetic data load) automatically — no manual step needed, but
   it takes longer than a normal SQL Server cold start; give it a few
   minutes before expecting `reconengine-backend`'s `/health` to succeed.
6. Free/starter plan caveats: `reconengine-backend` on the free web plan
   spins down after 15 minutes idle (~30–60s cold start on the next
   request); `reconengine-sql-db` as a private service with a disk
   requires a paid tier (Render doesn't offer free persistent disks) —
   worth knowing before relying on this longer-term.
