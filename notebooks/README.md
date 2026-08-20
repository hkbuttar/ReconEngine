# notebooks/ — Research Notebook

`research.ipynb` — every result in this project consolidated into one
executable notebook. Every cell reads this project's own real output
files or calls its own real functions directly (e.g. the ingestion
validators, called live against deliberately bad rows) — nothing is
narrated or hand-typed. Executed end to end via `nbconvert` during this
build: **0 errors across 41 cells**, every number cross-checked against
the values already verified in each area's own README.

Covers, in order: real data acquisition, ingestion validation, lifecycle
gating, matching engine match rates, root-cause taxonomy, rule-based vs.
ML classification, LLM-assisted explanation/query (real captured outputs,
not re-executed — would require a live billed API call on every run),
invoice reconciliation, break aging, audit trail, monitoring/alerting,
lineage completeness, measured performance, the Qlik dashboard status,
the test suite, and — as its own dedicated section — every real bug
found and fixed during this project's build, how each was found, and
what the fix was.

## Regenerate

The notebook is built programmatically from `build_notebook.py` (via
`nbformat`) rather than hand-edited as JSON — change that script, not
`research.ipynb` directly, then rebuild:

```bash
python3 notebooks/build_notebook.py
jupyter nbconvert --to notebook --execute --inplace notebooks/research.ipynb
```

The DB-independent sections (everything except cell outputs that read
already-generated CSVs — none of which need a live connection) run
anywhere; nothing in the notebook itself requires the `reconengine-sql`
container to be running, since it reads the pipeline's already-committed
real output files rather than querying the database live.
