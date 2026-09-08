# Fixed Decision Membership

Baseline: `a36e3d42722fe793a7c681a1f8fc25ff3551228d` (main).
Analysis: schema 2, `fixed-decision-membership-v1`.
New shadow: schema 2, `relative-valuation-v2`, experiment version 2.
Selection policy: `production-country-minimum-v1`.

## Audited defects

Baseline `evaluation_analysis.py:_analyze_run_horizon` filtered to
`priced_pairs` before deriving bucket counts, bucket assignments and
`_top_metrics` / `_run_bucket_metrics`. The country denominator was already
original-X, but gate groups disappeared when every member was unpriced.
Baseline `challenger_analysis.py:_analyze_paired_run` passed only priced IDs to
its own `_top_metrics`. Factor-coverage groups were also survivor-defined.

Baseline `experiments.py:build_challenger_experiment_snapshot` sorted by gate,
adjusted score, ticker and company ID. It did not apply production's sequential
minimum-country replacement policy, and company-ID ties were not production's
stable input-order ties. Even neutral adjustments could change selection.

## X first, Y second

`DecisionMembership.from_snapshot` accepts only the immutable X universe and a
complete permutation of its ranks (recorded challenger ranks for a shadow).
`DecisionCohort` holds ordered stable company IDs. Country and gate groups use
X attributes. Y is attached afterward by company ID; analysis rejects mismatched
identity, rank or decision metadata. Missing members remain in the cohort.
The production X builder records eligible members only; corrected sidecars
reject ineligible or mismatched inputs instead of inventing another selection
population. All new selection inputs come from the same contemporaneous
deduplicated research items as production, before outcomes exist.

Unchanged boundary rules:

- Top ten: original ranks 1 through min(10, N).
- Top/bottom decile: first/last ceil(N * 0.1) recorded ranks.
- Buckets: 10 at N >= 50, 5 at N >= 25, 2 at N >= 10, otherwise 1 (0 if empty).
- Bucket index: floor(zero-based rank index * bucket count / original N).
- Existing missingness rank-decile labels retain their ceil(rank * 10 / N)
  rule. Y rank and grouping fields are validated against X before use.
- Country and gate-tier membership includes all X members of that group.
- Factor-coverage groups include all corresponding sidecar members, not just Y.

N is the complete relevant decision-time population, never the priced subset.
Ties already resolved in immutable ranks do not get resolved again from Y.
Later price revisions and analysis cutoffs may change observations, not members.
The existing coherent-history revision selector remains the source of selected Y.

## Coverage and return interpretation

Each run-level cohort records ordered `member_ids`, decision-time member count,
priced count, missing count, coverage percentage, fixed 1/N member weight,
observed weight, observed mean/median, exact equal-weight return and return status.
Aggregate coverage counts member-date observations; return aggregation remains
run-level, never pooled security returns across dates.

An observed-member mean is a descriptive ranking diagnostic, even if the
overall run passes eligibility. It is not an investable portfolio return.
`exact_equal_weight_return_pct` is null for empty or incompletely observed
cohorts. No zero imputation, replacement or survivor-weight renormalization.
A paired exact portfolio delta requires complete champion AND challenger
portfolios on the same eligible run. Partial IC uses common observed pairs with
the original-X denominator. The minimums remain 70% AND 50 companies overall,
and 70% AND 20 companies for country aggregation, plus overall-run eligibility.
No new smaller-cohort eligibility threshold or profitability claim is introduced.

Existing universe and same-country reference means are unchanged observed-Y
references, now explicitly distinguished from exact fixed-cohort returns.
Their representativeness and investment interpretation remain separate work.
JSON retains legacy diagnostic key names where useful with explicit scope and
coverage alongside them. Country `equal_weight_return_pct` now requires full
coverage; `observed_mean_return_pct` retains the partial diagnostic.

## Shared production selection

`selection.py:rank_and_select` performs the original stable base sort, sequential
country-minimum replacements and stable selected-list sort. Long-term base order
is gate tier, descending effective score, ascending ticker, stable input order.
Replacement dedup identity stays `(ticker, country)`; original object identity
still determines exclusion from the unselected tail. Production filters,
enrichment, issuer deduplication, scoring and gate assessments are unchanged.

As before, the full X ranking is the constrained selected prefix followed by the
remaining base-ranked tail. A quota-promoted lower-gate member can precede an
unselected higher-gate member at that prefix boundary. The selector preserves
even infeasible-constraint behavior and constraint iteration order. It does not
turn a minimum into a guarantee when too few eligible members exist.

Both champion and corrected challenger call that same selector with the same
universe, gate/country information, top-N and ordered minima. Only the effective
score differs. Neutral adjustments preserve the exact champion score, including
sub-rounding differences. Sidecars must reproduce recorded champion ranks and
selection before saving. Their loader recomputes and validates both selections.

New sidecars add ordered constraint configuration, policy version, per-row
original input order and both selected flags. Existing fields retain stable
company identity, linked X run ID, scores and both ranks. No raw fundamentals
are duplicated. A canonical configuration hash separates paired aggregates
with different selection configurations, in addition to experiment/model/horizon.

## Compatibility and persistence

- Immutable X schema and serialization remain unchanged. Internal production
  build-result metadata captures the selector input order for the new sidecar.
- V1 sidecars keep schema 1, original IDs, bytes and direct-order semantics.
  V1 ranking diagnostics use its recorded ranks, never a retrofitted v2 ranking.
  Its challenger portfolio is unavailable/unverified because exact historical
  shared-selection evidence was not recorded. V1 and v2 aggregates stay separate.
- A historical public portfolio is available only when X records a consistent
  `public_selection_size`, `public_limit`, eligible selected prefix and full ranks.
  This reads the recorded constrained prefix; it does not rerun a guessed policy.
  The absent historical policy version stays unverified. Missing evidence yields
  `membership_status=unavailable`, never inferred replacement membership.
- New analysis outputs use `data/evaluation-analysis/fixed-decision-membership-v1/`.
  CLI defaults, README and workflow output paths agree. Writers refuse old or
  mixed analysis versions at existing paths. Same-methodology derived latest
  analysis may still be refreshed from immutable inputs using an explicit cutoff.
- Experiment saves remain immutable and conflict-rejecting. Existing v1 data,
  historical analysis, X, Y, public reports and published pages are not rewritten.

## Offline acceptance and validation

Run `PYTHONPATH=src:tests python3 tests/test_fixed_decision_membership.py` for the
deterministic JSON demonstration. It uses only synthetic research and fixture Y.
Case A: the old concept yields ranks 31-37 from 70 survivors; corrected top
decile is ranks 1-10 with 0/10 observed and no replacements. Case B: all factor
adjustments are zero, legacy unconstrained top ten differs, and corrected
challenger equals the ordered FI:3-constrained champion exactly.

`tests/test_fixed_decision_membership.py` covers cohort boundaries, missing
members, empty groups, partial IC, both portfolios, neutral scores, country and
gate constraints, stable ties, score-driven changes, version separation,
historical cutoffs, identity checks and a baseline v1 serialization golden hash.
The existing report, eligibility and coherent-price-history tests remain relevant.
All validation is offline, including inherited Python subprocess socket guards.
Baseline fixture comparison uses fixed clocks across all five production
strategies, with/without FI:3 and First North, comparing public JSON, Markdown,
CLI output and supported X snapshots byte-for-byte.

No benchmark redesign, maturity/not_due repair, legacy Performance v1 repair,
FX redesign, concentration policy, factor/weight changes or second challenger
is included. These ranking diagnostics are not investment-performance claims.
