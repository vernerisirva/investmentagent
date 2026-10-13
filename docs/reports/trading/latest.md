# InvestmentAgent Trading Ideas

> Research triage only. Not financial advice.

_Short-term setup candidates based on momentum, liquidity, and catalysts._

## Metadata
- generated_at: 2026-10-13T06:38:55.407139+00:00
- provider: live
- fundamentals: finimpulse
- countries: SE, FI
- limit: 10
- enrichment_limit: 30
- enrichment: {'eligible_universe_size': 1, 'enrichment_budget': 30, 'refresh_budget': 30, 'selected_candidates': 0, 'attempts': 0, 'successful_enrichments': 0, 'cutoff_tie_count': 1, 'cutoff_tie_excluded': 0, 'cache_enabled': True, 'cache_hits': 928, 'cache_misses': 2, 'cache_max_age_days': 45, 'eligible_companies': 1, 'cached_companies': 1, 'fresh_companies': 1, 'stale_companies': 0, 'missing_companies': 0, 'oldest_retrieved_at': '2026-10-02T05:23:47.439515Z', 'newest_retrieved_at': '2026-10-02T05:23:47.439515Z', 'country_coverage': {'SE': {'eligible': 1, 'cached': 1, 'fresh': 1, 'stale': 0, 'missing': 0}}}
- fundamentals_cache: {'enabled': True, 'max_age_days': 45}
- include_first_north: True
- min_market_cap: None
- max_market_cap: None
- sector: None
- strategy: trading
- min_country_counts: {'FI': 3}
- evaluation: {'run_id': 'evaluation-a0a9bae37e1cde7e471197dd', 'scoring_model_version': 'nordic-ranking-v1', 'decision_at': '2026-10-13T06:38:55.407139Z'}

## Source Checks
- nasdaq nordic live data: ok - universe coverage: total=938, SE=741, FI=197; STO/main_market=410, HEL/main_market=149, STO/first_north=331, HEL/first_north=48; source=https://api.nasdaq.com/api/nordic/screener/shares
- fundamentals enrichment: ok - eligible=1; budget=30; selected=0; attempts=0; successful=0; cache coverage=1/1 (fresh=1, stale=0, missing=0); cache hits=928; cache misses=2; cutoff ties=1 (0 excluded)
- finimpulse fundamentals: warning - No lookups attempted for Finimpulse fundamentals
- eodhd fundamentals: warning - EODHD_API_KEY is not configured
- valuation fallback: warning - 0 fallback valuation enrichments; no fallback lookups attempted
- free fundamentals: warning - No lookups attempted for Yahoo-style fundamentals
- valuation fallback: warning - 0 fallback valuation enrichments; no fallback lookups attempted

## Watchlist

## #1 Hacksaw (HACK)

`SE` | Nasdaq Stockholm | `main_market`

**What the company does:** Hacksaw AB (publ) operates as a B2B technology platform and game development company in Sweden and Czech Republic. It develops and distributes games comprising digital slots, scratch cards, and instant win games for private and state-owned iGaming operators, as well as develops remote gaming servers. The company was incorporated in 2017 and is based in Stockholm, Sweden.

**Score:** -8.5
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- High P/B

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (HACK.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)
