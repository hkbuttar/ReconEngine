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
3. **Azure SQL free tier** — the real path for an actual reachable-from-
   the-internet deployment (what `render.yaml`'s
   `RECONENGINE_ODBC_CONNECTION_STRING` would point at in production).
   Needs an Azure account — your call, same reasoning as the Qlik Cloud
   account decision earlier in this project. Once provisioned, load the
   schema the same way as the local container:
   `sqlcmd -S <azure-server>.database.windows.net -d reconengine -U <user> -i sql/schema.sql`
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
2. Provision SQL Server somewhere reachable from Render (Azure SQL free
   tier — see above).
3. In the Render dashboard: **New +** → **Blueprint**, point it at the
   repo. Render reads `render.yaml` and creates the web service.
4. Set `RECONENGINE_ODBC_CONNECTION_STRING` (pointed at your Azure SQL
   instance) and `ANTHROPIC_API_KEY` in the Render dashboard — both are
   `sync: false` in `render.yaml`, deliberately not committed.
5. Free plan: the web service spins down after 15 minutes idle (~30–60s
   cold start on the next request) — fine for a portfolio deployment,
   worth knowing before relying on it longer-term.
