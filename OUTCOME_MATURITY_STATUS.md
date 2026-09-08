# Outcome Maturity and Retrieval Status

## Defect and Scope

`_initial_outcome()` records an initial `not_due` placeholder. Before this repair,
normal and paired analysis inferred maturity from that persisted string; stale
placeholders could remain apparently not due long after the exit session closed.
Evaluations without an outcome store were omitted entirely. The coherent-history
repair already made actual budget deferrals `coherent_history_pending`, but a
dry-run skipped that transition and still reported mature initial records as
`not_due`.

This repair changes status accounting, not investment decisions, price/return
arithmetic, eligibility thresholds, benchmark logic, or production selection.

## Cutoff-relative Lifecycle

Maturity is determined only by decision time, country/exchange calendar, the
configured session horizon, and an explicit cutoff. The existing entry rule is
the first eligible session close strictly after decision time. The target is
exactly `horizon.sessions` market sessions after entry. Maturity begins at that
target close, including the established Stockholm half-day close. Weekends,
Stockholm/Helsinki holidays, and market time zones use the existing calendar.
Stored fixed sessions must agree with those reconstructed decision-time sessions.

| Condition at cutoff | Effective status | Availability |
| --- | --- | --- |
| Target close is later than cutoff | `not_due` | Not yet mature |
| Target closed; no visible coherent evidence or stale initial placeholder | `coherent_history_pending` | Awaiting retrieval |
| Target closed; budget deferral was recorded by cutoff | `coherent_history_pending` | Budget-deferred; existing explicit detail retained |
| Fetch attempted, missing entry or exit | `missing_entry` / `missing_exit` | Unavailable/incomplete |
| Fetch attempted, symbol unresolved or adjustment unsupported | `symbol_unresolved` / `corporate_action_unsupported` | Unavailable |
| Provider/request failed | `provider_error` | Failed |
| Coherent endpoint pair is visible by cutoff | `priced` | Available |

Maturity does not imply availability. Pending, failed, and unavailable members
remain in the fixed X denominator and contribute no observed return. Neither
replacement selection, survivor-weight renormalization, nor zero-return filling
is allowed. Original overall 70%/50 and country 70%/20 thresholds are unchanged.

## Historical Analysis

Normal analysis uses `data_cutoff`, or `generated_at` when no explicit data cutoff
is supplied, for both revision visibility and maturity. A January horizon can be
not mature at a January cutoff and mature but unpriced at a February cutoff.
Later retrieval or a correction cannot make its return visible earlier.

The established coherent-history revision selector runs first, unchanged. It
retains its fail-closed behavior for missing historical revision provenance.
After selection, ephemeral analysis inputs normalize stale labels using fixed
sessions. Future or unmatured price evidence cannot contribute a return. These
views are not outcome-store revisions and are never persisted as Y.

When no Y exists, analysis derives missing company/horizon inputs from X and the
canonical strategy horizons (or validated stored horizon definitions when an
outcome set exists but is not yet visible). This creates no price evidence and
does not invent a security, rank, selection, or return. Future X and sidecars do
not enter earlier-cutoff analyses. Both champion and challenger use the same
selected Y evidence and the same cutoff-relative views.

Standalone challenger analysis accepts an explicit `data_cutoff`. For backwards
compatibility, omission means the latest timestamp actually recorded in its
supplied inputs, not wall-clock time; the resolved cutoff is reported. An empty
standalone invocation needs an explicit cutoff. Normal report generation always
supplies the report's resolved cutoff.

## Planner and Persistence

The planner uses the same maturity predicate. Unmatured horizons are not fetched;
priced coherent outcomes are reused; mature missing coherent histories retain
the existing deterministic priority and exact API-call budget, including symbol
alternatives. Changing derived status creates no extra provider request.

Dry-run makes no writes or requests. Its lifecycle is as of the requested
scheduling cutoff; planned/unfetched mature work is awaiting retrieval, and
budget-excluded work is explicitly deferred. Normal refresh retains existing
coherent-history persistence, endpoint provenance, and append-only revisions.
Its final lifecycle cutoff includes actual evidence-completion timestamps,
reported separately from the scheduling cutoff, rather than calling a new wall
clock solely to age records. No legacy live repricing is performed automatically.

Recorded schema-1/2 Y remains readable and byte-preserved. Initial `not_due`
records are historical placeholders, not timeless assertions of current
maturity. Their original revision identities remain unchanged. The existing
pending status and budget detail already express the required persisted state;
there is no new Y schema or return-methodology version and no historical rewrite.

The **derived analysis contract does change**: schema 3 requires status
methodology `cutoff-maturity-v1` alongside unchanged membership methodology
`fixed-decision-membership-v1`. JSON/Markdown overwrite guards and aggregate
checks reject missing or incompatible status methods. Default CLI/workflow
outputs use `fixed-decision-membership-v1/cutoff-maturity-v1/`; earlier analysis
files stay intact and are not presented as having originally contained these
diagnostics. Legacy Performance v1 is untouched and is not skill evidence.

## Diagnostics and Acceptance

JSON and Markdown expose evaluation counts, company-horizon totals, not-mature,
mature/priced, mature/pending, budget-deferred subset, unavailable, and failed
states. Run summaries retain eligible and partial counts with fixed denominators.
Budget detail is evidence of a recorded deferral; unknown historical reasons are
classified as awaiting retrieval, never guessed to have been quota failures.

The deterministic acceptance case uses 100 ranked X members, initial unfetched
Y, and a later cutoff beyond maturity. Historical stored labels remain
`not_due`; corrected views report 100 mature pending records, zero prices, zero
coverage, and no eligible run. An earlier cutoff still correctly reports 100
not mature. Calendar, budget/alternate-symbol, cache reuse, revisions, historical
cutoff, fixed-cohort, eligibility-boundary, and version-protection tests exercise
the actual production/analysis paths offline.

Older return-analysis tests previously chose generation times before their own
fixture retrieval timestamps. Their generation clocks were moved after those
retrievals; return expectations and eligibility thresholds were not weakened.

## Next Methodology Task

Representative benchmarks remain out of scope. After that framework is reviewed
and merged, freeze factors, weights, gates, top-N, country constraints, challenger,
benchmarks, horizons, and eligibility thresholds. Allow roughly 4-5 trading weeks
minimum and 8-12 weeks preferably for observation; checkpoints do not authorize
tuning merely because early performance disappoints.
