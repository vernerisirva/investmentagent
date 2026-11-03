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

## Performance v1 Ledger

The legacy scorecard's ledger, `docs/data/performance/ledger.json`, had the same
defect at a slower pace. Every run rewrote it whole, and it grew by about 0.44 MB per
trading day: one market snapshot of roughly 335 KB plus that day's picks. On
2026-11-03 it was 41.8 MB. It would have passed GitHub's 50 MiB warning around
2026-12-09 and its 100 MiB limit around 2027-06-03.

`investmentagent performance update` now keeps the ledger, by default, in
`docs/data/performance/ledger/`:

| Path | Content |
| --- | --- |
| `index.json` | `schema_version` plus `ledger_storage`: the ordered partition lists with entry counts and SHA-256 digests, the digest of the reconstructed ledger, and the digest of the single file that seeded it |
| `picks/<year>/<report date>.json` | That report date's picks, in ledger order |
| `market-snapshots/<year>/<date>.json` | That date's market snapshot |

No file grows with the number of dates. A run writes the day's picks and snapshot,
rewrites only the earlier report dates whose outcomes it resolved, and rewrites the
index, which grows by about 400 bytes per date. A report date's partition stops
changing once all four horizons have resolved.

`investmentagent.performance.load_ledger` reads either layout. A path ending in
`.json` is a single-file ledger; any other path is a partitioned directory. For the
partitioned layout it checks every digest, path, identity and count. It returns a
dictionary whose canonical serialization and nested key order are identical to what
the single-file reader returns.

The writer:

- refuses to drop a report date or a snapshot date that the existing index lists, or
  to lose a pick from a report date;
- refuses picks that are not in ascending report-date order, because the layout could
  not reproduce that order;
- reloads its own output before returning.

Ledger values, outcome updates, country benchmark returns and the rendered scorecard
are unchanged. The Performance v1 ledger is not part of the frozen Performance v2
methodology.

### Legacy single file and migration

`ledger.json` is kept unchanged as the last single-file ledger; see
`docs/data/performance/LEGACY_SINGLE_FILE_LEDGER.md`. The first scheduled run after
this change finds no partitioned index, so it reads `ledger.json` through
`--legacy-ledger` and writes the partitions. It never writes `ledger.json`.

The index records the file's SHA-256. Every later run refuses to start if
`ledger.json` has changed since, so an outdated writer of the single file fails loudly
instead of diverging. A partitioned directory that has files but no index is never
reseeded.

`--ledger <file>.json` still reads and writes a single file for ad hoc work. It is
unbounded and is not used by the scheduled workflow.

## Publication Order

The daily workflow now publishes in two commits:

1. `reports: publish daily watchlist <date>`: reports, X, benchmark plans and
   challenger sidecars, pushed immediately after generation.
2. `reports: update performance records <date>`: the legacy scorecard and its
   partitioned ledger (only if that step succeeded), the outcome stores, and the
   partitioned analysis (only if the analysis step succeeded).

Both use `.github/scripts/publish-staged.sh`, which refuses to commit a staged file
GitHub would reject (over 100 MiB) and warns above GitHub's 50 MiB recommendation. A
failure in a derived step can no longer discard the day's decision-time evidence,
and a later scheduled run the same day skips because the reports already exist.

The legacy scorecard step continues on error, so a failure in it no longer skips the
Performance v2 refresh and analysis. The final step fails the run after publication
whenever the legacy scorecard, the outcome refresh or the analysis failed.
