# InvestmentAgent Trading Ideas

> Research triage only. Not financial advice.

_Short-term setup candidates based on momentum, liquidity, and catalysts._

## Metadata
- generated_at: 2026-11-03T14:36:47.110441+00:00
- provider: live
- fundamentals: finimpulse
- countries: SE, FI
- limit: 10
- enrichment_limit: 30
- enrichment: {'eligible_universe_size': 345, 'enrichment_budget': 30, 'refresh_budget': 30, 'selected_candidates': 30, 'attempts': 30, 'successful_enrichments': 29, 'cutoff_tie_count': 8, 'cutoff_tie_excluded': 0, 'cache_enabled': True, 'cache_hits': 925, 'cache_misses': 3, 'cache_max_age_days': 45, 'eligible_companies': 345, 'cached_companies': 344, 'fresh_companies': 310, 'stale_companies': 34, 'missing_companies': 1, 'oldest_retrieved_at': '2026-09-16T05:06:52.285650Z', 'newest_retrieved_at': '2026-11-03T14:36:46.779372Z', 'country_coverage': {'SE': {'eligible': 319, 'cached': 319, 'fresh': 285, 'stale': 34, 'missing': 0}, 'FI': {'eligible': 26, 'cached': 25, 'fresh': 25, 'stale': 0, 'missing': 1}}}
- fundamentals_cache: {'enabled': True, 'max_age_days': 45}
- include_first_north: True
- min_market_cap: None
- max_market_cap: None
- sector: None
- strategy: trading
- min_country_counts: {'FI': 3}
- evaluation: {'run_id': 'evaluation-824e4d4c4dd5961514399624', 'scoring_model_version': 'nordic-ranking-v1', 'decision_at': '2026-11-03T14:36:47.110441Z'}

## Source Checks
- nasdaq nordic live data: ok - universe coverage: total=936, SE=739, FI=197; STO/main_market=409, HEL/main_market=149, STO/first_north=330, HEL/first_north=48; source=https://api.nasdaq.com/api/nordic/screener/shares
- fundamentals enrichment: ok - eligible=345; budget=30; selected=30; attempts=30; successful=29; cache coverage=344/345 (fresh=310, stale=34, missing=1); cache hits=925; cache misses=3; cutoff ties=8 (0 excluded)
- finimpulse fundamentals: warning - 29/30 Finimpulse lookups parsed; valuation support 29/29; direct valuation 29/29; proxy inputs 29/29; missing valuation support 0/29
- eodhd fundamentals: warning - EODHD_API_KEY is not configured
- valuation fallback: warning - 0/1 fallback lookups parsed; 0 fallback valuation enrichments; fallback source: EODHD_API_KEY is not configured
- free fundamentals: warning - No successful Yahoo-style fundamentals lookups (0/1 Yahoo-style lookups parsed): HTTP Error 401: Unauthorized
- valuation fallback: warning - 0/1 fallback lookups parsed; 0 fallback valuation enrichments; fallback source: No successful Yahoo-style fundamentals lookups (0/1 Yahoo-style lookups parsed): HTTP Error 401: Unauthorized

## Watchlist

## #1 KABE Group B (KABE B)

`SE` | Nasdaq Stockholm | `main_market`

**What the company does:** KABE Group AB (publ.), together with its subsidiaries, manufactures and sells caravans, motorhomes, and camping accessories in Sweden, the United Kingdom, Germany, Norway, Finland, Denmark, Poland, and internationally. The company operates in three segments: Caravans and Motorhomes, Accessories, and Other. It is involved in the production, development, logistics, marketing, and sale of caravans, motorhomes, transport vehicles, and other mobile units, as well as camping accessories and equipment. The company offers its products under the KABE, Adria, Sun Living, Coachman, Affinity, and KAMA Fritid brand names. It exports and distributes its products through local independent dealerships. The company was formerly known as KABE AB (publ.) and changed its name to KABE Group AB (publ.) in July 2018. KABE Group AB (publ.) was founded in 1957 and is headquartered in Tenhult, Sweden.

**Score:** 9.5
**Data quality:** partial

### Reasons
- Strong intraday momentum (+17%)
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- Thin liquidity

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (KABE-B.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #2 ByggPartner Gruppen (BYGGP)

`SE` | Nasdaq First North Growth Market Sweden | `first_north`

**What the company does:** ByggPartner Gruppen AB (publ) operates as a construction company in Sweden. The company engages in construction of community properties such as schools, health care and social care; remodeling and construction of premises, office environments, and housing; industry; and wood construction. It also operates in the contracting and construction services, as well as scaffolding and the manufacture of house components. The company was formerly known as ByggPartner i Dalarna Holding AB (publ) and changed its name to ByggPartner Gruppen AB (publ) in June 2022. ByggPartner Gruppen AB (publ) was founded in 1992 and is headquartered in Borlänge, Sweden.

**Score:** 8.75
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (BYGGP.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #3 Duroc B (DURC B)

`SE` | Nasdaq Stockholm | `main_market`

**What the company does:** Duroc AB (publ), through its subsidiaries, acquires and develops industrial and trading companies in Sweden, rest of the Nordic countries, rest of Europe, the United States, and internationally. The company offers polypropylene-based staple fibers for the construction, furniture, filtration, and automotive industries; polypropylene-based colored filament yarn and staple fibers; fiber-based textiles for professional crop cultivation; PVC and PU-coated textiles for use in the fashion industry, protective clothing, hospital beds, car interiors, dental chairs, furniture, and wall coverings; and advanced tube bending machines for the automotive, aerospace, and furniture industries, as well as the heating, ventilation, and air conditioning industry. It also supplies machine tools, tools, machine service, and support to mechanical engineering companies; work holding tools, such as lathe chucks, threading tools, and collets; and diesel engines for industrial and marine applications, as well as associated spare parts, service, and repairs. In addition, the company engages in the provision of maintenance services for railway wheels of locomotives, as well as passenger and freight cars; street-sweeping machines and road maintenance; renovation and new manufacturing of industrial components based on laser surface treatment technology for the power, mining/steel, pulp/paper, offshore, aviation, and manufacturing industries; and customization of complete automation solutions. Duroc AB (publ) is headquartered in Stockholm, Sweden.

**Score:** 8
**Data quality:** partial

### Reasons
- Strong intraday momentum (+13.23%)
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- Thin liquidity

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (DURC-B.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #4 Surgical Science Sweden (SUS)

`SE` | Nasdaq First North Growth Market Sweden | `first_north`

**What the company does:** Surgical Science Sweden AB (publ) develops and markets virtual reality simulators and customized training solutions for evidence-based medical training in Europe, North and South America, Asia, and internationally. The company offers Angio Mentor simulator for endovascular training; BRONCH Express, a portable version of BRONCH mentor simulator; ARTHRO Mentor for arthroscopic surgery skills acquisition; BRONCH Mentor, a simulator for optimizing bronchoscopy training; GI Mentor, a simulator for GI Endoscopy; HYST Mentor for True-To-Life diagnostic and therapeutic hysteroscopy training; URO Mentor, a virtual reality simulator for endourology training; EndoSim, a realistic scope simulator; FlexVR, a flexible and portable training platform which is designed to teach basic and advanced skills for robotic surgery; and LAP Mentor provides a wide array of laparoscopic training cases. It also provides LapSim training system comprising LapSim Haptic simulator that provides laparoscopic training; LapSim essence, a portable and ready-to-use VR simulator; and LapSim 360, which provides a high-immersion virtual reality training experience; MentorLearn, an end-to-end educational platform that makes simulation course management; and LapSim ST, a training system that prepares students for the operating room. In addition, the company offers PELVIC Mentor simulator provides anatomy and pelvic exam training; Perc Mentor suite for image-guided interventions; RobotiX Mentor for practice the motor and cognitive skills for surgeons; Simball Box, which combines with digitally collected metrics into a training tool; Spine Mentor, a training simulator for minimal invasive spine surgery; TEE Express, designed to teach Trans-Esophageal Echocardiography procedure using a TEE probe; TraumaVR, an ultimate mix of manikin and VR simulation; and Ultrasound Mentor for ultrasound training with multiple medical specialties. Surgical Science AB was founded in 1997 and is based in Gothenburg, Sweden.

**Score:** 8
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (SUS.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #5 Cedergrenska (CEDER)

`SE` | Nasdaq First North Growth Market Sweden | `first_north`

**What the company does:** Cedergrenska AB (publ) provides education services in Sweden. It operates preschool, elementary, and upper secondary schools, as well as operates gymnasiums and adult education centers. Cedergrenska AB (publ) was founded in 2017 and is headquartered in Stockholm, Sweden.

**Score:** 7.25
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (CEDER.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #6 Bonava B (BONAV B)

`SE` | Nasdaq Stockholm | `main_market`

**What the company does:** Bonava AB (publ), together with its subsidiaries, operates as a residential developer in Germany, Sweden, Finland, Estonia, Latvia, and Lithuania. The company constructs, develops, and sells multi-family and single-family homes, as well as semi-detached houses. It serves consumers and institutional investors. The company was founded in 1930 and is headquartered in Stockholm, Sweden.

**Score:** 7
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (BONAV-B.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #7 Dustin Group (DUST)

`SE` | Nasdaq Stockholm | `main_market`

**What the company does:** Dustin Group AB (publ) engages in online information technology business in Sweden, Finland, Denmark, the Netherlands, Norway, and Belgium. The company offers various hardware, software, financing solutions, subscription services, and other related services and solutions. It serves large companies and the public sector. The company was founded in 1984 and is headquartered in Nacka, Sweden. Dustin Group AB (publ) operates as a subsidiary of AxMedia AB.

**Score:** 7
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (DUST.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #8 Outokumpu Oyj (OUT1V)

`FI` | Nasdaq Helsinki | `main_market`

**What the company does:** Outokumpu Oyj produces and sells various stainless-steel products in Finland, Germany, Italy, the United Kingdom, other European countries, North America, the Asia-Pacific, and internationally. It operates through Europe, the Americas, Ferrochrome, and Other operations segments. The company offers cold rolled coils, strips, and sheets; hot rolled coils, strips, and plates; quarto plates; precision strips; and specialized components, such as welded stainless-steel I-beams, H-beams, hollow-section tubes, bent profiles, duprof structural sections, hardened and customized press plates, suction roll shells, and blancs and disks. It also provides stainless steel powder which includes Supra 316L, Dura 17-4PH, Ultra 904L, Therma 253MA, Dura 4116, and Ni-free austenitic stainless-steel powder, ferritic grades as well as tailored product; and nickel-based alloys for environments in the process industry, oil and gas, and electric vehicles. In addition, the company offers cutting, polishing and brushing, welding, machining, plate bending and other services. Further, its products are used in various applications, including commercial kitchens, cooking, food industry, and home appliances; automotive and transportation; building and infrastructure; energy; marine; and heavy industries. Outokumpu Oyj was founded in 1910 and is headquartered in Helsinki, Finland.

**Score:** 3.25
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (OUT1V.HE)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #9 Tieto Oyj (TIETO)

`FI` | Nasdaq Helsinki | `main_market`

**What the company does:** Tieto Oyj operates as a software and digital engineering company in Norway, Sweden, Finland, and internationally. It operates through four segments: Tieto Tech Consulting, Tieto Banktech, Tieto Caretech, and Tieto Indtech Services. The Tieto Tech Consulting segment provides business advisory and design, data engineering, and other software research and development services. The Tieto Banktech segment offers Banking-as-a-Service platform and software products for payments, cards, wealth management, financial crime prevention, and credit domains. The Tieto Caretech segment provides modular, open, and interoperable software for customers in the health and social care sectors. The Tieto Indtech segment offers software and services to various industries, such as case management, pulp, paper, and fiber; and supports processes, including billing and invoicing and industry messaging, as well as purchase-to-pay process automation. It serves automotive, banking and financial services, education, energy and utilities, healthcare and welfare, manufacturing, public sector, pulp, paper, fibre, packaging and tissue, and telecom sectors. The company was formerly known as TietoEVRY Oyj and changed its name to Tieto Oyj in March 2026. Tieto Oyj was incorporated in 1968 and is headquartered in Espoo, Finland.

**Score:** 1
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (TIETO.HE)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #10 Stora Enso Oyj R (STERV)

`FI` | Nasdaq Helsinki | `main_market`

**What the company does:** Stora Enso Oyj provides renewable solutions for the packaging, biomaterials, wooden constructions, and paper industries in Finland and internationally. It operates through Packaging Materials, Packaging Solutions, Biomaterials, Wood Products, Forest, and Other segments. The company's Packaging Materials segment offers virgin and recycled fiber replace fossil-based materials, renewable and recyclable packaging materials for food and beverage, and transport packaging. Its Packaging Solutions segment develops and sells fiber-based packaging products and services, including converting carton and corrugated boards for packaging solutions for retail, e-commerce, and industrials. The company's Biomaterials segment provides various pulp for packaging, paper, tissue, specialties, and hygiene products; and tall oil and turpentine from biomass. Its Wood Products segment offers wood-based solutions, including digital tools for design and construction of building projects with wood; applications for windows and doors; and pellets for sustainable heating solutions. The company's Forest segment engages in sustainable forest management, as well as supplies wood. The company's Other segment produces electricity and heat. It serves packaging manufacturers, brand owners, retailers, converters, and construction companies. The company was incorporated in 1996 and is headquartered in Helsinki, Finland.

**Score:** 0.25
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (STERV.HE)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)
