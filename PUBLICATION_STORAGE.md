# Bounded Publication Storage

## Defect and Scope

The scheduled job republished the whole schema-4 benchmark analysis as one JSON file
every day. Every evaluation run adds eight run-horizon entries, so the file grew by
about 2.05 MB per trading day. On 2026-11-02 and 2026-11-03 it reached 100.76 MiB,
GitHub rejected the push (GH001), and because the same commit carried the day's
decision-time evidence, those two days' X, benchmark plans and challenger sidecars
were never published.

Outcome stores had a second, slower version of the same problem. Each refresh
re-stamped every budget-deferred record with a new calculation time, which created a
new content-addressed revision per record per run without any new evidence. The
2026-09-09 long-term store grew from 6.7 MB to 34.4 MB in 17 trading days.

This repair changes how results are stored and published. It does not change X,
selection, scores, benchmark plans, returns, maturity, eligibility, revision
selection or any analysis value. It is a reliability change allowed during the
methodology freeze.

## Partitioned Analysis

`investmentagent evaluate analyze` now writes, by default,
`data/evaluation-analysis/fixed-decision-membership-v1/cutoff-maturity-v1/representative-benchmarks-v1/performance-v2/`:

| Path | Content |
| --- | --- |
| `index.json` | Every top-level analysis field except `run_metrics`, plus `analysis_storage`: the ordered partition list with SHA-256 digests and the digest of the reconstructed analysis |
| `runs/<decision date>/<strategy>/<evaluation run>/<horizon>.json` | One run metric |
| `performance-v2.md` | The unchanged Markdown rendering |

Each run metric repeats the analysis status cutoff in `lifecycle.status_cutoff`.
Partitions omit that one field and the loader restores it from the index, so a run
whose values did not change keeps a byte-identical file from one day to the next.

`investmentagent.analysis_storage.load_analysis` reads either layout. For the
partitioned layout it checks every digest and identity, restores the factored field
and returns a dictionary whose canonical serialization is byte-identical to what the
single-file writer would have produced. The writer reloads and compares its own
output before returning, never drops a run horizon that an existing index already
lists, and refuses to overwrite an index of another schema or methodology.

`--output-json` still writes a single file for ad hoc work. It is unbounded and is
not used by the scheduled workflow.

### Legacy single file

`performance-v2.json` and `performance-v2.md` beside the new directory are the last
single-file outputs (generated 2026-10-30T06:03:51Z, commit `db28ebe`). They are kept
unchanged as historical artifacts; see `LEGACY_SINGLE_FILE_ANALYSIS.md` there.

## Outcome Stores

A refreshable record that is deferred by the API budget again, while its current
record is already `coherent_history_pending` with the budget-deferral detail, is now
kept as it is instead of being re-stamped. Every other transition is unchanged:
`not_due` to pending, pending to priced or failed, and failed back to pending when a
failed security is deferred, each still writes a revision. Existing revisions are
never removed.

At any cutoff the selected record has the same status, detail, prices and return as
before, so lifecycle counts, coverage, eligibility, IC and benchmark values are
unchanged. Only `methodology.selected_outcomes_hash`, a digest of which revision
identities were selected, can differ, because fewer redundant revisions exist.

## Publication Order

The daily workflow now publishes in two commits:

1. `reports: publish daily watchlist <date>`: reports, X, benchmark plans and
   challenger sidecars, pushed immediately after generation.
2. `reports: update performance records <date>`: the legacy scorecard, outcome
   stores and, only if the analysis step succeeded, the partitioned analysis.

Both use `.github/scripts/publish-staged.sh`, which refuses to commit a staged file
GitHub would reject (over 100 MiB) and warns above GitHub's 50 MiB recommendation. A
failure in a derived step can no longer discard the day's decision-time evidence,
and a later scheduled run the same day skips because the reports already exist.
