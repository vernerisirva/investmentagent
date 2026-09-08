# Representative Benchmarks v1

Methodology: `representative-benchmarks-v1`. Primary:
`constraint-matched-random-v1`. Analysis schema 4; plan schema 1.
This preregistration is fixed before prospective evidence. It tests selection
within the same decision-time opportunity set, not passive-market outperformance.

## Hierarchy

1. **Primary: constraint-matched random selection.** 1000 draws through the exact
   production `rank_and_select` function. The only removed signal is score:
   retain long-term gate priority, country minima, top-N, and sequential country
   replacements, including the existing handling of infeasible constraints.
2. **Secondary: gate-qualified equal weight.** The pre-top-N eligible X cohort.
3. **Secondary: opportunity-universe equal weight.** All original Performance v2
   X members, never the subset whose outcomes were obtained.
4. **Secondary: exposure-matched opportunity baseline.** Equal within fixed
   alternative pools; weight those pools by selected-security exposure.
5. **Secondary: matched peers.** Each selected security compared with its fixed
   alternative pool. The portfolio-weighted peer mean and exposure benchmark
   coincide under this shared rule; they are not independent confirmations.

**EXTERNAL_PASSIVE_BENCHMARK: DEFERRED_PENDING_LICENSE**

No proprietary index data, index provider, ETF proxy, index cache, or external
benchmark API requirement exists in v1. Nasdaq strategy benchmarking requires
an appropriate license; current contemplated provider terms do not establish
public redistribution/publication rights. A later licensed external series
requires a separate versioned contextual analysis, not an addition to v1's
headline evidence. The existing stock-outcome provider is unchanged.

## What Gates Mean Here

Production trading X has already passed its trading-setup eligibility screen,
filters, scoring availability and deduplication. Long-term X similarly contains
the final eligible opportunity set; its four quality tiers are **ordering
priorities**, not hard exclusions. Country constraints can promote a lower-tier
name, and random selection must preserve this exact behavior.

Consequently, gate-qualified EW and opportunity EW currently have identical
members. This is explicitly reported, not hidden by inventing a new gate.
The value of upstream excluded securities' gates is **not identifiable** from
current X/Y. A demonstration of different pre-gate and post-gate returns cannot
be claimed from this dataset. The primary random null does isolate ranking
conditional on the existing gates and selection policy.

## Reproducible Random Membership

Seed = SHA-256 of canonical JSON
`[benchmark_methodology, random_methodology, evaluation_run_id]`.
For draw indices 0 through 999, pseudo-rank is the byte digest of UTF-8
`seed:draw_index:company_id`. Input order is canonical company ID order.
Selection key is gate priority, pseudo-rank, ticker. Thus process hash seeds,
filesystem traversal order and Y have no effect. Output membership is sorted
by company ID, with a digest covering all 1000 portfolios.

The same random null is used for champion and relative-valuation-v2 because
both obey the same recorded production policy. A different evaluation identity
has a different deterministic sequence. The frozen quantile convention is
linear interpolation at `(n - 1) * q`; champion percentile uses half credit
for ties, divided by all 1000 draws. These are descriptive null comparisons,
not independent-date significance tests.

## Exposure and Peer Rules

The alternative pool excludes the entire portfolio being compared. Each
selected security follows the fixed hierarchy:

1. country + venue + official Nasdaq size segment
2. country + venue
3. country

Use a level only if all its fields exist and at least five alternative X
securities match. Record skipped levels and reasons. Never fall across countries.
If the last level fails, that exposure is unavailable; its weight is not
redistributed. A 7 SE / 3 FI portfolio therefore retains 70% / 30% country
weights, including when some outcomes are absent.

Current X persists country, Main Market / First North venue, and sector.
Sector is deliberately not used because its classification contract is not
needed for this bounded version. An optional validated `nasdaq_size_segment`
field supports large/mid/small when genuinely recorded in X. Existing production
does not supply it. No current/later market cap, present-day metadata lookup,
sector inference, or size enrichment is performed. Existing serialized X bytes
remain unchanged when size is absent.

Fallback can relax venue/size exposure matching; the actual chosen stratum and
original selected exposures remain visible. Do not interpret a country-only
fallback as size-neutral performance.

## Decision-Time Plans

Plans live inside the evaluation root:
`<date>/<strategy>/benchmarks/representative-benchmarks-v1/<run_id>.json`.
The watchlist producer creates them after X/optional challenger construction
and before any outcome refresh. Plans contain the X content hash, evaluation
identity/time, cohort IDs, ordered production policy and original input order,
selected identities, challenger identity/content hash, seed/count/algorithm and
draw digest, exposure pools/weights/fallback evidence, provenance and hierarchy.
They contain no realized returns or raw financial observations.

Loading regenerates the plan from immutable X and its recorded selection
evidence, verifies the exact champion reproduction and challenger linkage,
and rejects incompatible/tampered plans. It never replaces an existing plan
with a later one. A missing challenger remains unverified even if a later
analysis discovers an experiment that was not included in the saved plan.

## History and Prospective Evidence

Old snapshots without plans are reconstructed only from their own X and, where
available, a validated schema-2 relative-valuation experiment. No plan is written
back. Opportunity and exposure/peer diagnostics can exist with a recorded public
prefix; the random null requires the stronger recorded shared-selector policy
and original input-order evidence. Missing evidence means unverified, not an
assumption about today's configuration.

- `retrospective`: reconstructed after the decision, even if deterministic.
- `fixture`: deterministic test producer, never live investment evidence.
- `prospective_unscheduled`: live producer outside natural scheduled production.
- `prospective`: live producer in the repository's scheduled GitHub workflow,
  recording event, run ID, repository and workflow source SHA in the plan.

The first naturally generated prospective plan after reviewed merge starts the
frozen observation clock. Metadata is retained audit evidence, not a
cryptographic attestation of the GitHub service. Confirm the referenced natural
run when recording activation. Never pool these provenance classes, different
selection configurations, strategies, models, or horizons into one headline.

## Outcomes, Completeness and Statistics

Reuse the unchanged coherent stock-outcome revision selection and cutoff-based
maturity logic. No new price pipeline, repricing or FX conversion.
Only already usable outcomes attach to fixed IDs.

Exact equal-weight portfolio/cohort returns require every member and a nonempty
cohort. Otherwise expose the original denominator, observed/missing counts,
coverage, observed weight and a clearly labelled observed-member mean.
Weighted alternative diagnostics expose the known fixed-weight contribution,
not a zero-imputed full return or renormalized portfolio.

The primary random distribution requires **100% of the underlying nonempty
eligible X universe**, a verified selector, coherent return methodology, and the
unchanged overall 70%/50 analysis guard. Report total/complete/incomplete draw
counts regardless; complete-draw survivor diagnostics are non-headline.
A complete primary-null sample is intentionally stricter than ranking IC.

Headline excess requires both sides complete and analysis eligible.
Security-vs-peer arithmetic is available only when that security and its entire
fixed peer cohort are observed. This supplies simple internal adjusted
selection diagnostics without introducing a residual model or a new IC policy.
Raw score/rank IC remains unchanged; country ranking guards remain 70%/20.

All portfolio means and differences use local-currency stock returns:
`mean_local_return_pct` and local excess. A mixed SEK/EUR mean is not a
base-currency wealth return. Costs, spread and slippage are still excluded.

## Legacy and Output Isolation

New default outputs are under
`fixed-decision-membership-v1/cutoff-maturity-v1/representative-benchmarks-v1/`.
Schema 4 cannot overwrite schema 3, and schema 3 cannot overwrite schema 4,
in JSON or Markdown. Existing legacy functions remain readable separately.
New outputs do not consume old survivor-defined benchmark fields as baselines.

Performance v1 is `LEGACY_NON_AUTHORITATIVE`. Its existing files are preserved;
future scorecard rendering carries a prominent quarantine notice. No historical
discrepancy is repaired and no v1 data enters the new benchmark analysis.

## Operational Activation and Freeze

Main's scheduled workflow stages the evaluation root, including new plans,
and uses the new analysis path. Keep the stock API budget of 20 unchanged.
After reviewed merge, an ancestor-only fast-forward of the scheduler branch to
merged main may synchronize the exact reviewed workflow without another commit
or manual production dispatch. Verify no scheduler-only changes/report loss.

The reviewed merge activates the methodology freeze defined in
`METHODOLOGY_FREEZE.json`. Until the first natural prospective plan:
**METHODOLOGY FROZEN - PROSPECTIVE SAMPLE PENDING ACTIVATION**.
Allow 4-5 trading weeks minimum, preferably 8-12 weeks, from that plan's decision
timestamp. Around weeks 12-13 the earliest 60-session cohorts become useful;
126/252-session long-term evidence needs longer.

Do not tune factors, weights, gates, top-N, country minima, challenger, null,
peer rules, horizons or eligibility after poor early results. Reliability,
monitoring, documentation and demonstrably non-semantic fixes remain allowed.
A genuine measurement defect must explicitly document any freeze break.

Known issuer/share-class concentration, ticker/country identity collisions,
historical selected-prefix evidence limits, absent-currency cache lookup and
generic failed-reprice labels remain separate considerations. New plans fail
closed on ambiguous selector identities rather than changing production policy.
