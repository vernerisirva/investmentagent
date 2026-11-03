# Price-Fetch Scheduling

## Defect and Scope

Outcome refresh may send at most 20 EODHD requests per run. Three scheduling defects
wasted that budget between 2026-10-08 and 2026-11-03:

- **No backoff.** A security whose request priced nothing kept the oldest unpriced
  evaluation date, so it sorted first and was retried every run. Five FI securities
  that never priced (four HTTP 404s and one unresolved symbol) were requested every
  day. By 2026-10-30, 11 of 16 executed calls went to previously failed securities.
- **Unused estimates.** A two-word ticker has two symbol candidates, so the plan
  reserved two calls for it. It almost always resolved on the first candidate, and
  the reserved call was lost: 28 of 340 budgeted calls went unused.
- **Country order.** Ties were broken by company ID, an ISIN, so every FI security
  (and other non-SE ISINs) was requested before any SE security. Priced coverage on
  2026-10-30 was 40.6% of FI mature records against 4.1% of SE.

This repair changes only when evidence is requested. It does not change X, the fixed
entry and exit sessions, the single-response return calculation, outcome statuses,
eligibility, benchmark plans, analysis cutoffs or the 20-request budget.

## Order

Refreshable work is still grouped per security, and a single request prices every due
outcome of that security. Tasks keep the existing priority (unestablished entry,
shortest due horizon, earliest end date, oldest unpriced evaluation date). Remaining
ties are now broken by `SHA256(company_id|market)` instead of the company ID, so equal
work is ordered independently of country, venue and identifier.

## Retry Backoff

A fetch day for a security is a UTC day on which a request returned a priced or a
failed record (`provider_error`, `symbol_unresolved`, `missing_entry`, `missing_exit`,
`corporate_action_unsupported`). After `n` consecutive fetch days that priced nothing,
the security is not requested again until `min(2**(n-1), 32)` days after the last one:
1, 2, 4, 8, 16, then 32 days. Any priced record ends the backoff.

The state is derived from stored outcome revisions only. It is deterministic, needs no
new file, and cannot drift from the evidence. Failures that the provider returned
without sending a request (missing API key, open error circuit) are not counted.

A security in backoff is deferred exactly like budget-deferred work. Its records keep
the existing `coherent history pending: API-call budget exhausted` status, and
lifecycle counts are unchanged. The fetch plan reports `retry_backoff_until`, and the
refresh summary reports `work_deferred_by_retry_backoff`.

## Budget

Tasks are fetched in order while the next task's estimated calls fit the calls
actually used so far. Estimates are upper bounds, so a call that a multi-candidate
estimate did not need goes to later tasks and the hard limit still holds. Every
fetched task uses at least one unit, even if the provider sent no request, so an open
error circuit cannot mark the whole backlog failed in one run.

## Workflow

Both caches are restored with `actions/cache/restore` and saved with
`actions/cache/save` under `if: always()`: fundamentals right after generation, price
histories right after the outcome refresh. A failed later step no longer discards that
day's requests. If the outcome refresh or the analysis fails, a final step fails the
job after everything else has been published, so the failure is visible instead of
silent.

## Transition

Securities that already failed enter backoff on the first run after deployment. Almost
all never-requested securities are now SE (656 of 659 on 2026-11-03), so the existing
FI-heavy priced sample is rebalanced only as the remaining first pass completes.
Partial coverage diagnostics remain country-skewed until then.
