# InvestmentAgent Trading Ideas

> Research triage only. Not financial advice.

_Short-term setup candidates based on momentum, liquidity, and catalysts._

## Metadata
- generated_at: 2026-11-17T17:05:36.510018+00:00
- provider: live
- fundamentals: finimpulse
- countries: SE, FI
- limit: 10
- enrichment_limit: 30
- enrichment: {'eligible_universe_size': 375, 'enrichment_budget': 30, 'refresh_budget': 30, 'selected_candidates': 30, 'attempts': 30, 'successful_enrichments': 30, 'cutoff_tie_count': 10, 'cutoff_tie_excluded': 9, 'cache_enabled': True, 'cache_hits': 925, 'cache_misses': 2, 'cache_max_age_days': 45, 'eligible_companies': 375, 'cached_companies': 375, 'fresh_companies': 308, 'stale_companies': 67, 'missing_companies': 0, 'oldest_retrieved_at': '2026-09-25T05:06:25.164636Z', 'newest_retrieved_at': '2026-11-17T17:05:36.229800Z', 'country_coverage': {'SE': {'eligible': 340, 'cached': 340, 'fresh': 273, 'stale': 67, 'missing': 0}, 'FI': {'eligible': 35, 'cached': 35, 'fresh': 35, 'stale': 0, 'missing': 0}}}
- fundamentals_cache: {'enabled': True, 'max_age_days': 45}
- include_first_north: True
- min_market_cap: None
- max_market_cap: None
- sector: None
- strategy: trading
- min_country_counts: {'FI': 3}
- evaluation: {'run_id': 'evaluation-da8c26e979abe6c1bb67c675', 'scoring_model_version': 'nordic-ranking-v1', 'decision_at': '2026-11-17T17:05:36.510018Z'}

## Source Checks
- nasdaq nordic live data: ok - universe coverage: total=935, SE=737, FI=198; STO/main_market=408, HEL/main_market=150, STO/first_north=329, HEL/first_north=48; source=https://api.nasdaq.com/api/nordic/screener/shares
- fundamentals enrichment: ok - eligible=375; budget=30; selected=30; attempts=30; successful=30; cache coverage=375/375 (fresh=308, stale=67, missing=0); cache hits=925; cache misses=2; cutoff ties=10 (9 excluded)
- finimpulse fundamentals: ok - 30/30 Finimpulse lookups parsed; valuation support 30/30; direct valuation 30/30; proxy inputs 30/30; missing valuation support 0/30
- eodhd fundamentals: warning - EODHD_API_KEY is not configured
- valuation fallback: warning - 0 fallback valuation enrichments; no fallback lookups attempted
- free fundamentals: warning - No lookups attempted for Yahoo-style fundamentals
- valuation fallback: warning - 0 fallback valuation enrichments; no fallback lookups attempted

## Watchlist

## #1 Pricer B (PRIC B)

`SE` | Nasdaq Stockholm | `main_market`

**What the company does:** Pricer AB (publ) provides in-store digital solutions in Europe, the Middle East and Africa, the Americas, and Asia and Pacific. The company provides electronic shelf labels, such as Pricer SmartTAG Color, Pricer Avenue, and Pricer HangTAG; Pricer Plaza, a cloud-based platform for scalable management, monitoring, and integration of a digital in-store system; and The Pricer platform, an in-store digital platform. It also offers attachment solutions for furniture, rails, adapters, and holders of shelf-edge; Pricer Shelf Vision, an artificial intelligence powered cloud cameras to monitor in-stores; and Pricer StoreLink provides optical access point to supports direct connection to Pricer Plaza. The company markets and sells its products through direct sales and resellers. Pricer AB (publ) was incorporated in 1991 and is headquartered in Stockholm, Sweden.

**Score:** 11
**Data quality:** partial

### Reasons
- Strong intraday momentum (+21.81%)
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- Thin liquidity

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (PRIC-B.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #2 Surgical Science Sweden (SUS)

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

## #3 Bonava B (BONAV B)

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

## #4 Dustin Group (DUST)

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

## #5 HEBA B (HEBA B)

`SE` | Nasdaq Stockholm | `main_market`

**What the company does:** Heba Fastighets AB (publ), together with its subsidiaries, engages in the real estate business in Sweden. It also develops, owns, manages, and leases youth housing, rental housing, nursing homes, and community properties in the Stockholm region and Mälardalen Valley. The company was incorporated in 1952 and is headquartered in Stockholm, Sweden.

**Score:** 7
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (HEBA-B.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #6 Humble Group (HUMBLE)

`SE` | Nasdaq Stockholm | `main_market`

**What the company does:** Humble Group AB (publ) develops, produces, and distributes fast-moving consumer goods in Sweden and internationally. It operates through four segments: Future Snacking, Sustainable Care, Quality Nutrition, and Nordic Distribution. The Future Snacking segment offers food, snack, and confectionery products. The Sustainable Care segment provides personal care and household products, such as skincare, oral care, hair care, and personal care products. The Quality Nutrition segment offers sports nutrition products and ingredients, as well as supplements for athletes and consumers. The Nordic Distribution segment provides a range of fast-moving consumer goods through a network of wholesalers and distributors. The company also sells ingredients and other raw materials. The company offers its products through grocery retailers, distributors, and online. The company was formerly known as Bayn Group AB (publ) and changed its name to Humble Group AB (publ) in April 2021. Humble Group AB (publ) was incorporated in 2009 and is based in Stockholm, Sweden.

**Score:** 7
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (HUMBLE.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

## #7 John Mattson Fastighetsföret. (JOMA)

`SE` | Nasdaq Stockholm | `main_market`

**What the company does:** John Mattson Fastighetsföretagen AB (publ) operates as a residential property company in Sweden. The company owns, develops, and manages rental apartments, as well as commercial premises and leasehold properties in municipalities, including Lidingö, Sollentuna, Stockholm, Nacka, and Upplands Väsby. John Mattson Fastighetsföretagen AB (publ) was founded in 1944 and is headquartered in Lidingö, Sweden.

**Score:** 7
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (JOMA.ST)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)

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

## #10 Lumo Kodit Oyj (LUMO)

`FI` | Nasdaq Helsinki | `main_market`

**What the company does:** Lumo Kodit Oyj operates as a private housing investment company in Finland. The company rents apartments and offers housing services under the Lumo brand name. It also offers broadband internet connection services, as well as car sharing services. The company was formerly known as Kojamo Oyj and changed its name to Lumo Kodit Oyj in March 2026. Lumo Kodit Oyj was founded in 1969 and is headquartered in Helsinki, Finland.

**Score:** 0.25
**Data quality:** partial

### Reasons
- High live turnover
- Trading strategy boost: liquidity and momentum signals make this more relevant for a short-term watchlist.

### Risks
- None provided.

### Evidence
- [Nasdaq Nordic listing source](https://api.nasdaq.com/api/nordic/screener/shares) (nasdaq)
- [Finimpulse fundamentals lookup (LUMO.HE)](https://developers.finimpulse.com/v1/statistics/general/) (finimpulse)
