# Coherent Adjusted-Price Histories For Performance v2

## Baseline And Scope

- Implementation branch: `codex/coherent-price-histories`.
- Base: `291490a4e2725cf58103b0a2e7a7a4d7f5605878`, current GitHub main fetched on 2026-09-07.
- Original checkout: clean `main` at `ef10ab82c117acab65ac86272067bd7333e886ae`; not moved or edited.
- Baseline evaluation, outcome, outcome-store, price-cache, and analysis schemas were all 1.
- The audit and diagnostic scripts in `InvestmentAgent-Audit-2026-09-07` were inspected read-only. Its `test_c_adjustment_vintages` was run against the unmodified implementation, without executing the script's artifact-writing main block.
- No production workflow, price API call, historical repricing, scoring change, or data-file rewrite is part of this delivery. No merge or push to either production branch.

## Root Cause And Corrected Invariant

The old cache accepted one adjusted value per date indefinitely. The planner requested only missing dates and reconstructed histories from those independently cached values. The outcome calculator froze a previously observed numeric adjusted entry. A provider's later adjustment of that entry therefore remained invisible to an exit-only request.

The corrected invariant is: **both endpoints of a newly calculated return must come from the same accepted response batch**. An existing coherent batch covering both dates is reusable. Two independent dates are never sufficient, even with equal provider names or retrieval timestamps.

The immutable objects are the evaluation and challenger decisions, security identity, ranks, decision timestamp, execution convention, entry session, target exit session, and horizon. A retrospective vendor adjusted-close number is not immutable across retrievals. Each observation *within* its recorded history remains immutable.

## Provider Contract

EODHD documents a per-symbol daily date-range response with inclusive `from`/`to` bounds. `adjusted_close` accounts for splits and dividends; raw OHLC does not. The documented response is an array, with no adjustment-version identifier or pagination protocol for this endpoint. [Official EOD documentation, verified 2026-09-07](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes).

The actual assumption is consistency **within one accepted response**, not independent proof of the provider's adjustment arithmetic. The local response UUID and history hash are not vendor adjustment-version IDs. Alternate symbol attempts remain separate responses. Future pagination or segmented fetching must not concatenate results under this contract without additional evidence.

EODHD completion timestamps come from an injectable clock after each HTTP response. Calculation timestamps are read separately. The fixture provider simulates one response per call and uses a deterministic simulated clock. Invocation `--retrieved-at` is a scheduling cutoff, not the claimed completion time of every later request.

Currency is still supplied by the existing security reference's country inference, explicitly labelled `security_reference_country_inference`. This repair does not pretend that the EOD endpoint independently confirms the listing's currency.

## Schemas And Storage

- `price_histories.py`: immutable history schema **2**; normalized observations, separate raw closes, stable company/ISIN, provider/symbol/exchange/market, requested range, actual sessions, completion, response UUID, content hash, currency/provenance, and adjustment convention.
- A batch ID hashes the normalized metadata, including retrieval identity and completion. Its content hash excludes retrieval timestamps so identical content is identifiable without conflating distinct retrievals.
- The same recorded response is idempotent. Reusing its response ID with changed content or metadata fails. A new response with identical prices retains separate provenance, including when timestamps happen to match.
- Existing schema-1 cache files remain untouched and unverified. The coherent archive is an adjacent `*.histories-v2.json` file. No inference from a collection of legacy timestamps is used to promote rows.
- Outcome and outcome-store schemas are **2**. Return methodology is `single-response-adjusted-close-v1`; old records are classified as `legacy-adjusted-close-unverified-v1`.
- Each repaired priced outcome contains the fixed sessions, exact numeric endpoints, calculation time, history identity/metadata, endpoint observations and their IDs, and the reproducible gross ratio. Accepted partial histories also retain their batch metadata. Unresolved outcomes contain no return.
- An outcome store retains current records plus prior revisions. Each changed record links its predecessor. Writes cannot drop previously persisted versions or mutate immutable decision/session fields. Writes are atomic; failed replacement leaves the old file intact.
- Evaluation and challenger sidecar schemas remain unchanged. Analysis schema remains 1 with explicit methodology/revision/cutoff metadata added; metric formulas and eligibility rules are unchanged.

Complete histories stay in the operational cache, not public Git or `docs/`. Public outcome evidence includes endpoints, not the complete price series. It remains possible to reproduce an existing return after cache eviction. Without the complete history, its full-series content hash cannot be independently recomputed; the retained endpoint evidence and outcome identities can be checked.

## Planning And Budget

The planner first resolves each outstanding endpoint pair against coherent stored histories, then groups the remaining work globally by security and market. One inclusive entry-through-exit range can satisfy multiple runs, strategies, and horizons. Cached pairs are not stitched together with a newly fetched endpoint.

The existing priority order and 20-call workflow budget are retained, including estimates for alternate symbol attempts. Known symbols can be reused without treating symbol metadata as proof of adjustment compatibility. A provider exceeding its estimate still fails the explicit budget check.

New due outcomes deferred by the budget are `coherent_history_pending`, with no fabricated return. Already priced coherent outcomes remain unchanged when a requested repricing is budget-deferred; the deferred fetch plan reports that work. Wider coherent ranges may fetch more rows than an exit-only request, but do not inherently require more per-security API calls.

Diagnostics distinguish reusable coherent outcome pairs, due pairs without a covering history, legacy records skipped, and due legacy records lacking coherence metadata. These categories can overlap: a legacy outcome needs repaired provenance even if an independently retained newer batch exists. `cache_hits` counts endpoint uses in coherent pairs, not independent date hits. The fetch plan is authoritative for requested ranges and budget deferral.

The pre-existing session calculation is memoized by decision/market/horizon inside the outcome module, avoiding repeated full-calendar walks during migration validation. No calendar, holiday, entry, exit, or horizon rule changed.

## Revisions And Analysis Cutoffs

Routine refresh leaves completed coherent outcomes unchanged. Explicit `--reprice` requests fresh coherent responses for the bounded selection and appends revisions. Changed numeric endpoints are labelled `coherent_endpoint_revision`, with a return difference in percentage points when both old and new returns exist. A new retrieval with unchanged endpoints still retains its retrieval provenance. Replaying the exact recorded response does not append another equivalent result.

No split or dividend is inferred from a difference in price. A correction is not an automatic permanent corporate-action exclusion. Missing endpoints, missing adjusted values, symbol/currency conflicts, or malformed provenance remain unresolved and retryable. Earlier valid and unsupported records remain available in the revision history.

No tolerance suppresses endpoint revisions. Ratio validation uses relative `1e-12` and absolute `1e-10` percentage-point tolerances solely for binary floating-point roundoff. Provider decimal rounding is not concealed by a broad economic tolerance. An exact common multiplicative rebasing preserves the ratio within that tight numerical tolerance.

Both analysis modules call the same selector: `latest-calculation-visible-at-data-cutoff-v1`. Only one return methodology is selected, and each run/security/horizon contributes at most once. Mixed methodology inputs without an explicit selection fail. The normal and paired outputs publish the same selected-outcome digest, method, revision policy, and cutoff.

Visibility requires decision, price retrieval, history completion, and calculation timestamps to be at or before the cutoff. The latest visible calculation is selected; equal calculation timestamps follow the retained revision order. A backdated invocation cannot make a later response visible earlier. Legacy records with insufficient retained history cannot fabricate a missing historical revision.

The CLI defaults the data cutoff to analysis generation time. The workflow now obtains analysis time after price refresh, rather than reusing the invocation-start timestamp. Library callers may explicitly choose `data_cutoff=None` for all retained data; that absence of a cutoff is recorded in the output.

## Legacy Compatibility And Explicit Reprocessing

Default refresh skips schema-1 outcome files, including their unfinished horizons, and reports the skipped count. It does not silently bless old prices or start repricing every historical run. New evaluation runs receive schema-2 outcomes normally.

Explicit legacy reprocessing writes a sibling `RUN_ID.coherent-v1.json`, retains the original legacy file byte-for-byte, and includes the legacy predecessor records in the new revision history. Subsequent normal refresh resumes the coherent sibling. Original `corporate_action_unsupported` records are not deleted.

Preview without credentials, writes, or API calls:

```sh
PYTHONPATH=src investmentagent evaluate outcomes --reprice --dry-run \
  --evaluation-root data/evaluations --outcome-root data/evaluation-outcomes \
  --price-cache .investmentagent/market-price-cache.json --max-price-api-calls 20
```

An actual requested reprocessing must specify `--run-id` or `--report-date`, omitting `--dry-run`. For example, after reviewing its dry run:

```sh
PYTHONPATH=src investmentagent evaluate outcomes --reprice --report-date YYYY-MM-DD \
  --max-price-api-calls 20
```

These commands are documentation, not authorization to execute a live refetch. Reprocessing was not run during this implementation.

The read-only preview at `2026-09-07T12:00:00Z`, against the committed dataset and an explicitly empty operational cache, inspected **46 runs / 85,856 records**. It found **0 demonstrably reusable pairs**, **1,862 due pairs requiring refetch**, and **1,862 due legacy pairs lacking batch metadata**. It planned at most 20 calls, deferred 386 security tasks, and executed **0 calls**. This does not establish the contents of the private production cache or prove existing returns wrong.

## Regression Evidence

The before cases below came from the audit's actual cache/planner/outcome counterexample, not an isolated formula. After cases use the repaired production path with deterministic fixture providers.

| Fixture | Old entry | New coherent entry / exit | Before | After |
| --- | ---: | ---: | ---: | ---: |
| Split | 100 | 50 / 50 | -50% | 0% |
| Dividend adjustment | 100 | 99 / 99 | -1% | 0% |
| Common rebasing | 100 | 50 / 55 | -45% | +10% |
| Provider correction | 100 | 90 / 110 | +10% | +22.222222% |

The new regression module covers retained/lost caches, unrelated same-timestamp batches, exit-only responses, shared windows, zero-call coherent reuse, append-only corrections, cutoff and paired-value identity, retryable unsupported histories, legacy dry runs and immutable originals, corruption, atomic failure, idempotent replay, provider clocks, and CLI safety.

Older tests that required frozen numeric entries, exit-only fetches, or permanent cache-revision exclusions were replaced with the corrected invariants. Separate retrievals are now compared for economic results rather than incorrectly requiring identical provenance. The existing 2,000-to-100-call shared-planning regression remains in place.

Validation results:

- `python3 -m pytest -q`: **450 passed in 12.82s**, including 36 new regression cases (baseline: 414 tests).
- Focused histories/outcomes/workflow checks excluding the large deduplication test: **94 passed, 1 deselected**. The large test passed in the complete suite.
- Actual fixture CLI commands: watchlist plus evaluation/sidecar recording; outcome refresh produced **20 priced outcomes using 5 simulated provider calls**; normal and challenger analysis each produced **4 horizon groups**, with identical selected-outcome digests. These tiny fixture groups remain subject to the unchanged eligibility thresholds.
- Fixture public watchlist JSON, evaluation files, and challenger sidecars were byte-identical to outputs from the unmodified audited base checkout.
- `python3 -m compileall -q src tests` and `git diff --check`: passed.
- `git diff --exit-code 291490a4e2725cf58103b0a2e7a7a4d7f5605878 -- data docs`: clean. No committed historical decision, outcome, analysis, watchlist, or legacy-performance file changed.
- The migration preview made zero external calls and wrote no cache or outcome files. No live credential was needed.

## Files Changed

| File | Responsibility |
| --- | --- |
| `src/investmentagent/price_histories.py` | New immutable response batches, metadata, endpoint evidence, archive validation and atomic writes |
| `src/investmentagent/market_prices.py` | Single-response provenance, actual clocks, numeric normalization |
| `src/investmentagent/market_price_cache.py` | Adjacent coherent archive; legacy records remain separate |
| `src/investmentagent/evaluation_outcomes.py` | Coherent global planner, schema-2 outcomes and revisions, migration preview, shared revision selector |
| `src/investmentagent/evaluation_analysis.py` | Methodology/cutoff selection and reporting only |
| `src/investmentagent/challenger_analysis.py` | The same revision/value selection boundary |
| `src/investmentagent/cli.py` | Bounded explicit repricing, dry run, analysis options, public-history-path guard |
| `.github/workflows/daily-public-watchlist.yml` | Cache path, explicit new methodology and post-refresh cutoff; unchanged quota |
| `tests/test_coherent_price_histories.py` | New production-path regressions |
| `tests/test_evaluation_outcomes.py` | Corrected old invariants and retained deduplication/cache-loss tests |
| `tests/test_daily_public_workflow.py` | Workflow boundary and no-automatic-repricing assertions |
| `COHERENT_PRICE_HISTORIES.md` | Design, compatibility, evidence, operations, and limitations |

## Limits And Next Repair

No incorrect production return has been established. Existing legacy adjustment consistency remains unverified until supported by new coherent evidence. The conservative response assumption does not independently verify provider corporate actions, ticker identity, or inferred currency.

The single JSON archive grows with retained response versions, and writes assume the existing single-writer workflow. Cache loss causes refetches for new work; it never silently recalculates completed outcomes. Historical windows outside the provider entitlement can remain unresolved within the existing budget.

Neither an ignored local directory nor an Actions cache is a confidentiality guarantee. Existing access controls are unchanged. Vendor retention/redistribution rights, Actions-cache reader access, and longer-term private archival storage still need an explicit decision; no new confidential-storage claim is made here.

The other audit findings remain open: survivor-based portfolio membership, champion/challenger country-selection mismatch, representativeness, maturity/backlog/date aggregation, issuer/currency comparability, benchmark design, and legacy benchmark discrepancies.

**Next bounded repair:** freeze portfolio membership at decision time, preserve intended weights when prices are missing, and apply an identical explicit selection policy to champion and challenger. Keep this separate from factor changes and benchmark redesign. It is not implemented in this branch.
