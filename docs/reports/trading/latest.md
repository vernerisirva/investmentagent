# InvestmentAgent Trading Ideas

> Research triage only. Not financial advice.

_Short-term setup candidates based on momentum, liquidity, and catalysts._

## Metadata
- generated_at: 2026-08-24T20:21:02.968724+00:00
- provider: live
- fundamentals: finimpulse
- countries: SE, FI
- limit: 10
- enrichment_limit: 30
- enrichment: {'eligible_universe_size': 372, 'enrichment_budget': 30, 'refresh_budget': 30, 'selected_candidates': 30, 'attempts': 30, 'successful_enrichments': 30, 'cutoff_tie_count': 39, 'cutoff_tie_excluded': 21, 'cache_enabled': True, 'cache_hits': 0, 'cache_misses': 930, 'cache_max_age_days': 45, 'eligible_companies': 372, 'cached_companies': 30, 'fresh_companies': 30, 'stale_companies': 0, 'missing_companies': 342, 'oldest_retrieved_at': '2026-08-24T20:20:35.335308Z', 'newest_retrieved_at': '2026-08-24T20:21:02.957435Z', 'country_coverage': {'SE': {'eligible': 338, 'cached': 27, 'fresh': 27, 'stale': 0, 'missing': 311}, 'FI': {'eligible': 34, 'cached': 3, 'fresh': 3, 'stale': 0, 'missing': 31}}}
- fundamentals_cache: {'enabled': True, 'max_age_days': 45}
- include_first_north: True
- min_market_cap: None
- max_market_cap: None
- sector: None
- strategy: trading
- min_country_counts: {'FI': 3}
- evaluation: {'run_id': 'evaluation-386d52d6101679f8de62dfbb', 'scoring_model_version': 'nordic-ranking-v1', 'decision_at': '2026-08-24T20:21:02.968724Z'}

## Source Checks
- nasdaq nordic live data: ok - universe coverage: total=938, SE=744, FI=194; STO/main_market=412, HEL/main_market=147, STO/first_north=332, HEL/first_north=47; source=https://api.nasdaq.com/api/nordic/screener/shares
- fundamentals enrichment: ok - eligible=372; budget=30; selected=30; attempts=30; successful=30; cache coverage=30/372 (fresh=30, stale=0, missing=342); cache hits=0; cache misses=930; cutoff ties=39 (21 excluded)
- finimpulse fundamentals: ok - 30/30 Finimpulse lookups parsed; valuation support 29/30; direct valuation 26/30; proxy inputs 29/30; missing valuation support 1/30
- eodhd fundamentals: warning - EODHD_API_KEY is not configured
- valuation fallback: warning - 0/1 fallback lookups parsed; 0 fallback valuation enrichments; fallback source: EODHD_API_KEY is not configured
- free fundamentals: warning - No successful Yahoo-style fundamentals lookups (0/1 Yahoo-style lookups parsed): HTTP Error 401: Unauthorized
- valuation fallback: warning - 0/1 fallback lookups parsed; 0 fallback valuation enrichments; fallback source: No successful Yahoo-style fundamentals lookups (0/1 Yahoo-style lookups parsed): HTTP Error 401: Unauthorized

## Watchlist

## #1 Biosergen (BIOSGN)

`SE` | Nasdaq First North Growth Market Sweden | `first_north`

**What the company does:** Biosergen AB (publ), a biotech company, develops antifungal drugs. Its lead product is BSG005, an antifungal drug candidate for the treatment of invasive fungal infections in immunocompromised patients, including AIDS, cancer, and transplant recipients. The company was founded in 2004 and is based in Solna, Sweden.

**Score:** 14
**Data quality:** partial

### Reasons
- Strong intraday momentum (+10.57%)
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (BIOSGN.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #2 Alvotech SDB (ALVO SDB)

`SE` | Nasdaq Stockholm | `main_market`

**What the company does:** Alvotech, through its subsidiaries, develops and manufactures biosimilar medicines for patients worldwide. It offers biosimilar products in the therapeutic areas of autoimmune, eye, and bone disorders, as well as cancer. The company provides AVT02, a high concentration, low-volume adalimumab formulation biosimilar to Humira to treat various inflammatory conditions, including rheumatoid arthritis, psoriatic arthritis, Crohn's disease, ankylosing spondylitis ulcerative colitis, and other indications; AVT04, a biosimilar to Stelara to treat various inflammatory conditions comprising psoriatic arthritis, Crohn's disease, ulcerative colitis, plaque psoriasis, and other indications; AVT06, a biosimilar to Eylea to treat various conditions, such as neovascular age-related macular degeneration, macular edema following retinal vein occlusion, diabetic macular edema and diabetic retinopathy; and AVT03, a biosimilar to Xgeva and Prolia to treat prevent bone fracture, spinal cord compression, and the need for radiation or bone surgery in patients with certain types of cancer, as well as prevent bone loss and increase bone mass. In addition, it offers AVT05, a biosimilar to Simponi and Simponi Aria to treat various inflammatory conditions, including rheumatoid arthritis, psoriatic arthritis, ulcerative colitis, and other indications; AVT16, a biosimilar to an Entyvio product for the treatment of adult patients with moderate to severe ulcerative colitis and moderate to severely active Crohn's disease; AVT23, a biosimilar to Xolair to treat allergic asthma, chronic spontaneous urticaria (CSU), and nasal polyp; and AVT33, a biosimilar to Keytruda product which is in early phase development. Alvotech was founded in 2013 and is based in Luxembourg, Luxembourg.

**Score:** 10
**Data quality:** partial

### Reasons
- Strong intraday momentum (+17.93%)
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (ALVO-SDB.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #3 Unibap Space Solutions (UNIBAP)

`SE` | Nasdaq First North Growth Market Sweden | `first_north`

**What the company does:** Unibap Space Solutions AB (publ) develops, produces, and sells computing hardware, software, and services for space missions in Sweden. It offers hardware, which includes application development systems (ADS) that enables mission customers to get a head start in their software development; iX5 solution, which is ideal for smaller spacecraft and operations in harsher environments; and iX10, a computer solution with the interfacing capacity of connecting anything to everything. The company also provides software comprising Unibap SCOS, an Ubuntu-based operating system that enables safe operation of Earth-based algorithms in space; and Unibap LOOM, an image preprocessing pipeline that enables real-time analysis of hyperspectral data in orbit. In addition, it offers Unibap remote access, a remote testing service for platform evaluation and software development; and Unibap remote support for integrating and using its hardware, software, and services, as well as D-Orbit's Unibap-powered in-orbit software demonstration services. It serves the defense and emergency industries, as well as civilian and commercial companies. The company was formerly known as Unibap AB (publ) and changed its name to Unibap Space Solutions AB (publ) in June 2025. Unibap Space Solutions AB (publ) was incorporated in 2013 and is based in Uppsala, Sweden.

**Score:** 9.75
**Data quality:** partial

### Reasons
- Strong intraday momentum (+34.61%)
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- Thin liquidity

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (UNIBAP.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #4 Cheffelo (CHEF)

`SE` | Nasdaq First North Growth Market Sweden | `first_north`

**What the company does:** Cheffelo AB (publ) provides subscription-based meal kit solutions to various customers in Sweden, Norway, and Denmark. The company operates under the Linas Matkasse, Godtlevert, Adams Matkasse, and RetNemt brand names. The company was formerly known as LMK Group AB (publ) and changed its name to Cheffelo AB (publ) in October 2023. The company was founded in 2008 and is headquartered in Sundbyberg, Sweden.

**Score:** 5.75
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (CHEF.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #5 Endomines Finland Oyj (PAMPALO)

`FI` | Nasdaq Helsinki | `main_market`

**What the company does:** Endomines Finland Oyj engages in the mining and exploration of gold deposits in Finland and the United States. The company holds interest in Karelian Gold Line located in Finland; Pampalo and Hosko mines located in Finland; four gold deposits in Idaho and Montana. The company was incorporated in 2021 and is based in Espoo, Finland.

**Score:** 5.75
**Data quality:** partial

### Reasons
- Strong intraday momentum (+11.18%)
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- High P/B

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (PAMPALO.HE)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #6 AAC Clyde Space (AAC)

`SE` | Nasdaq First North Growth Market Sweden | `first_north`

**What the company does:** AAC Clyde Space AB (publ) provides small satellite technologies and services in Sweden, the United Kingdom, rest of Europe, the United States, Asia, and internationally. It offers command and data handling, cubesat batteries, power system, PCDU, communications, solar arrays, cubesat structure, payloads, attitude determination and control systems (ADCS), electrical power systems, laser and radio communications systems, lightweight structure solutions, payload solutions, propulsion systems, and smallsat technologies, as well as on-board data handling solutions. The company also provides space data as a service; data delivery; mission design, manufacturing, and integration of components services; and launch and ground services. In addition, it operates EPIC spacecraft platform. The company offers its products and services under AAC clyde space, omnisys, spacequest, hyperion, space Africa, and spacemertic brand names. It serves the government, businesses, and educational organizations. The company was formerly known as ÅAC Microtec AB (publ) and changed its name to AAC Clyde Space AB (publ) in November 2019. AAC Clyde Space AB (publ) was incorporated in 2005 and is headquartered in Uppsala, Sweden.

**Score:** 1
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- Negative operating margin

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (AAC.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #7 ByggPartner Gruppen (BYGGP)

`SE` | Nasdaq First North Growth Market Sweden | `first_north`

**What the company does:** ByggPartner Gruppen AB (publ) operates as a construction company in Sweden. The company engages in construction of community properties such as schools, health care and social care; remodeling and construction of premises, office environments, and housing; industry; and wood construction. It also operates in the contracting and construction services, as well as scaffolding and the manufacture of house components. The company was formerly known as ByggPartner i Dalarna Holding AB (publ) and changed its name to ByggPartner Gruppen AB (publ) in June 2022. ByggPartner Gruppen AB (publ) was founded in 1992 and is headquartered in Borlänge, Sweden.

**Score:** 0.75
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- Thin liquidity

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (BYGGP.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #8 Enorama Pharma (ERMA)

`SE` | Nasdaq First North Growth Market Sweden | `first_north`

**What the company does:** Enorama Pharma AB (publ), a pharmaceutical company, develops, manufactures, and sells tobacco-free white snus in Sweden. It offers its products under the NIC-S brand name. The company was incorporated in 2006 and is based in Stockholm, Sweden.

**Score:** 0.75
**Data quality:** partial

### Reasons
- Positive intraday momentum (+8.47%)
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- Thin liquidity

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (ERMA.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #9 Elisa Oyj (ELISA)

`FI` | Nasdaq Helsinki | `main_market`

**What the company does:** Elisa Oyj provides telecommunications, information and communication technology (ICT), and online services in Finland, rest of Europe, and internationally. It operates through two segments: Consumer Customers and Corporate Customers. The company offers consumers with telecommunications and communications services, including fixed and mobile subscriptions, supplementary digital services, cable TV subscriptions, and entertainment services, as well as IT and communication solutions. It provides sedApta, supply chain management and operational planning software; camLine, an automation, MES, and data analytics software; CalcuQuote, a integrated software for sourcing, quoting, procurement, and supplier collaboration; and TenForce, a platform to strengthen safety culture and operational oversight across complex industrial environments. It also offers Polystar, an intelligent network analytics and optimization software. The company markets its solutions under Elisa IndustrIQ brand. Further, it provides Gridle, an AI-powered energy flexibility optimization service; and Elisa Kotiakku, that smooths out spikes in electricity spot prices and stores electricity generated by solar panels. In addition, the company offers automation solutions for network management and operation for mobile operators, industrial IoT solutions and distributed energy solutions. It serves consumers, corporates, and public administration organizations. Elisa Oyj was founded in 1882 and is headquartered in Helsinki, Finland.

**Score:** -2
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (ELISA.HE)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #10 Finnair Oyj (FIA1S)

`FI` | Nasdaq Helsinki | `main_market`

**What the company does:** Finnair Oyj is a Finland-listed main market Consumer Discretionary company on Nasdaq Helsinki.

**Score:** -9
**Data quality:** thin

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
