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
ties go to the security priced least recently, never-priced first, and then to
`SHA256(company_id|market)` instead of the company ID, so equal work is ordered
independently of country, venue and identifier.

Recency matters because a longer horizon maturing for the oldest run (60 sessions from
2026-12-02, 126 from 2027-03-11, 252 from 2027-09-09) gives every security the same
oldest unpriced date again. A fixed order alone then re-serves the securities that
were served first last time, each pricing one new record, while never-priced
securities, each worth dozens of records, wait. In the planner model this delayed
90% coverage of the first run from 2026-12-18 to 2027-02-05.

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

## ISIN-Verified Symbols

EODHD symbols were guessed from the ticker in the evaluation universe: the ticker plus
`.HE` or `.ST`, with spaces as hyphens or removed. When EODHD uses another code, for
example for a share class or a renamed instrument, the security never prices.
- **Waste:** EODHD charges a failed lookup like a successful one, so each attempt also
  used budget.
- **Affected on 2026-11-04:** five FI securities that are in every long-term X,
  KPYOSK, ILKKA, PALLAS, SAVOX and LEHTO (four HTTP 404s and one empty response).

A security is *symbol-seeking* when **all** of these hold:
- it has no symbol from an established outcome, the history archive or the legacy cache;
- it has never priced;
- at least one of its own fetch days failed (the same retry state as the backoff).

Symbol-seeking securities are looked up in EODHD's exchange symbol list for `HE` or
`ST`. That is one request for every active ticker of the exchange, with its ISIN where
EODHD has one. The list request:
- is made at the start of the run, before any price, whenever a symbol-seeking security
  exists on that exchange, whether that security is due today or in backoff;
- is made at most once per exchange in 28 days, whether it succeeded or not;
- is counted in the same 20-call budget. On those days it takes the call of the last
  fetch that would otherwise have fit. With no call left, nothing is requested or
  recorded and the next run tries again;
- is made only when the provider would actually send it. A missing key or an open error
  circuit is not an attempt.

Requesting the list before any price matters. The planner serves work by due date, and
a never-priced security collects so much due work that it sorts late. On 2026-12-01
the five FI securities sit at positions 363–655 of 912 tasks while about 16 fit the
budget, so a lookup made just before their own fetch would not happen for weeks.

One list decides every symbol-seeking security on that exchange. A mapping is accepted
only for **exactly one** listed row with the same ISIN, in the security's currency
(`EUR` for `HE`, `SEK` for `ST`), whose name shares at least one word with the
security's name (ignoring accents and words such as Oyj or Group). Otherwise the
security keeps its ticker guesses, and the reason is recorded: `not_listed`,
`ambiguous`, `currency_mismatch`, `name_mismatch`, `invalid_code` or `no_isin`.

A mapped symbol replaces the ticker guesses for that security alone, as one candidate
that needs one call.
- **No pinning:** a failed attempt records no symbol, exactly as a failed guess did, so
  it does not pin the security to the mapping.
- **Establishing a symbol:** only a priced response establishes the symbol, after which
  the security's own outcomes and archive supply it.
- **Precedence:** a security that has ever priced, or that has any established symbol,
  never consults a mapping, so its symbol cannot change.
- **Backoff:** unchanged. A mapping is tried at the security's next scheduled retry.

Decisions and list provenance (time, status, row counts and a SHA-256 of the parsed
list, never the token) are kept in
`data/evaluation-outcomes/symbol-mappings/eodhd-isin-v1.json`. The file is published with
the outcome stores but is not one: outcome discovery reads only the
`<report date>/<strategy>/` store layout and never parses `symbol-mappings/`. (Before
that rule, the 2026-11-05 and 2026-11-06 analyses failed on this file.) Each priced
outcome already records the `provider_symbol` it used.
The refresh summary reports `symbol_list_calls` and `isin_symbol_fetches`, and each plan
item reports its `isin_symbol`.

No return, entry, exit, status, horizon, eligibility or benchmark rule changes. A
security priced this way is the same ISIN-identified security, priced through the same
single-response adjusted-close method.

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
