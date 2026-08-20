# qlik/ — Qlik Sense Dashboard

## Status: fully specified, not yet running live

Everything scriptable from this environment is built and grounded in
real, verified numbers:

- `load_script.qvs` — a real Qlik load script against the live SQL
  Server schema, with deliberate `QUALIFY`/`UNQUALIFY` discipline
  documented in `data_model.md`.
- `data_model.md` — the associative model design: what links to what,
  and why several same-named SQL columns are deliberately kept from
  associating.
- `sheets.md` — the 4 required sheets (Accounting, Compliance,
  Operations, Lineage), each specified with real figures already
  computed and verified in earlier steps, not placeholder mockups.

**What's not done**: actually opening this in Qlik Sense and taking
screenshots. Verified live during this step:
**Qlik Sense Desktop has no macOS support** — Qlik Community's own
support articles confirm it's Windows-only (64-bit), with Qlik Cloud
(browser-based) or Windows virtualization as the only paths on a Mac.
This environment has no GUI and no Windows VM, so there's a hard ceiling
on what's buildable here — the original project plan anticipated this
exact gap (`README.md`'s already says Qlik Sense Desktop would be
"documented via screenshots/walkthrough," not run headlessly).

## Path forward (needs a decision only you can make)

Qlik Cloud has a free tier and works in any browser, including on this
Mac — but creating an account and connecting it to the local SQL Server
container (which would need to be reachable from Qlik Cloud, e.g. via
Qlik's Application Automation connector or a tunnel, since Qlik Cloud is
hosted, not local) is real setup work only you can do. Once that's in
place, `load_script.qvs` should work close to as-is (Qlik Cloud's script
editor uses the same load script language).

Until then, `data_model.md` and `sheets.md` stand as the complete,
reviewable design — everything a Qlik developer would need to build the
app in an afternoon once a Qlik Cloud connection exists.
