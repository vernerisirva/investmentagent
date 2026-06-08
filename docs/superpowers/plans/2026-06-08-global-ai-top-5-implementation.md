# Global AI Top 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separate daily `InvestmentAgent Global AI Top 5` report that ranks curated global AI stocks by long-term quality, valuation discipline, growth, AI relevance, and risk.

**Architecture:** Keep the Nordic watchlist and performance paths unchanged. Add a new `global_ai.py` feature module with its own curated universe loader, scoring model, report dataclasses, Markdown/JSON payload helpers, and Typer subcommand. Reuse `FinancialSnapshot`, `Company`, `CompanyResearch`, `Evidence`, `SourceCheck`, and the existing FinImpulse fundamentals parsing. Add one provider hook for explicit global symbols so the curated universe can call FinImpulse without Nordic suffix inference.

**Tech Stack:** Python 3.11+, Typer CLI, pytest, JSON package data, Markdown report publishing through GitHub Actions.

---

## File Structure

- Add `src/investmentagent/data/global_ai_universe.json`: curated global AI stock universe with explicit FinImpulse symbols.
- Add `src/investmentagent/global_ai.py`: universe loading, symbol enrichment, scoring, ranked report building, and report serialization helpers.
- Modify `src/investmentagent/fundamentals.py`: add explicit FinImpulse symbol lookup with fallback currency.
- Modify `src/investmentagent/renderers.py`: add Global AI Markdown and JSON renderers using existing formatting helpers where useful.
- Modify `src/investmentagent/cli.py`: add `investmentagent global-ai top-5`.
- Modify `.github/workflows/daily-public-watchlist.yml`: generate and publish the global AI report after Nordic reports.
- Add `tests/test_global_ai.py`: cover universe loading, scoring, ranking, source checks, and rendering payloads.
- Modify `tests/test_fundamentals.py`: cover explicit FinImpulse symbol lookup.
- Modify `tests/test_cli.py`: cover the new CLI command, saved Markdown, saved JSON, and required key behavior.
- Modify `tests/test_daily_public_workflow.py`: cover workflow generation, index links, and performance ledger isolation.

## Data Model

Use these dataclasses in `src/investmentagent/global_ai.py`:

```python
@dataclass(frozen=True)
class GlobalAIUniverseEntry:
    name: str
    ticker: str
    provider_symbol: str
    country: str
    exchange: str
    currency: str
    sector: str
    ai_category: str
    ai_thesis: str


@dataclass(frozen=True)
class GlobalAIScoreBreakdown:
    valuation: float
    quality: float
    growth: float
    ai_relevance: float
    risk_penalty: float
    data_quality_penalty: float
    total: float
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class GlobalAIReportItem:
    rank: int
    entry: GlobalAIUniverseEntry
    research: CompanyResearch
    score: GlobalAIScoreBreakdown
    valuation_summary: str
    quality_summary: str
    growth_summary: str
    risk_flags: tuple[str, ...] = ()
```

Return a report object from the build function:

```python
@dataclass(frozen=True)
class GlobalAIReport:
    items: tuple[GlobalAIReportItem, ...]
    metadata: dict[str, object]
    source_checks: tuple[SourceCheck, ...]
```

## Curated Universe

Create `src/investmentagent/data/global_ai_universe.json` as an array of objects. Start with a compact, reviewable universe that covers AI compute, semiconductor equipment, cloud platforms, enterprise AI software, and data platforms.

Initial entries:

```json
[
  {
    "name": "NVIDIA",
    "ticker": "NVDA",
    "provider_symbol": "NVDA",
    "country": "US",
    "exchange": "NASDAQ",
    "currency": "USD",
    "sector": "Semiconductors",
    "ai_category": "AI compute semiconductors",
    "ai_thesis": "Dominant accelerator platform for model training, inference, networking, and AI software ecosystems."
  },
  {
    "name": "Taiwan Semiconductor Manufacturing",
    "ticker": "TSM",
    "provider_symbol": "TSM",
    "country": "TW",
    "exchange": "NYSE",
    "currency": "USD",
    "sector": "Semiconductors",
    "ai_category": "AI compute manufacturing",
    "ai_thesis": "Leading advanced-node foundry behind many high-end AI chips and accelerators."
  },
  {
    "name": "ASML Holding",
    "ticker": "ASML",
    "provider_symbol": "ASML",
    "country": "NL",
    "exchange": "NASDAQ",
    "currency": "USD",
    "sector": "Semiconductor Equipment",
    "ai_category": "Semiconductor equipment",
    "ai_thesis": "Critical lithography supplier for advanced chips used in AI accelerators and high-performance computing."
  },
  {
    "name": "Microsoft",
    "ticker": "MSFT",
    "provider_symbol": "MSFT",
    "country": "US",
    "exchange": "NASDAQ",
    "currency": "USD",
    "sector": "Cloud Software",
    "ai_category": "Cloud AI platform",
    "ai_thesis": "Azure, Copilot, enterprise distribution, and model partnerships create broad AI monetization paths."
  },
  {
    "name": "Alphabet",
    "ticker": "GOOGL",
    "provider_symbol": "GOOGL",
    "country": "US",
    "exchange": "NASDAQ",
    "currency": "USD",
    "sector": "Internet Platforms",
    "ai_category": "Model/application platform",
    "ai_thesis": "Owns frontier model research, search distribution, cloud AI infrastructure, and TPU compute capacity."
  },
  {
    "name": "Amazon",
    "ticker": "AMZN",
    "provider_symbol": "AMZN",
    "country": "US",
    "exchange": "NASDAQ",
    "currency": "USD",
    "sector": "Cloud and Commerce",
    "ai_category": "Cloud AI platform",
    "ai_thesis": "AWS infrastructure, Trainium/Inferentia chips, and AI services provide platform-level AI exposure."
  },
  {
    "name": "Meta Platforms",
    "ticker": "META",
    "provider_symbol": "META",
    "country": "US",
    "exchange": "NASDAQ",
    "currency": "USD",
    "sector": "Internet Platforms",
    "ai_category": "Model/application platform",
    "ai_thesis": "Large-scale AI infrastructure, recommendation systems, open model strategy, and advertising optimization."
  },
  {
    "name": "Broadcom",
    "ticker": "AVGO",
    "provider_symbol": "AVGO",
    "country": "US",
    "exchange": "NASDAQ",
    "currency": "USD",
    "sector": "Semiconductors",
    "ai_category": "AI infrastructure hardware",
    "ai_thesis": "Custom accelerators, networking chips, and infrastructure software tied to hyperscale AI demand."
  },
  {
    "name": "Oracle",
    "ticker": "ORCL",
    "provider_symbol": "ORCL",
    "country": "US",
    "exchange": "NYSE",
    "currency": "USD",
    "sector": "Cloud Software",
    "ai_category": "Cloud AI platform",
    "ai_thesis": "Cloud infrastructure expansion and database footprint create enterprise AI infrastructure exposure."
  },
  {
    "name": "Palantir Technologies",
    "ticker": "PLTR",
    "provider_symbol": "PLTR",
    "country": "US",
    "exchange": "NYSE",
    "currency": "USD",
    "sector": "Data and Analytics",
    "ai_category": "Data and analytics platform",
    "ai_thesis": "AI platform and ontology layer target operational AI use cases across government and enterprises."
  },
  {
    "name": "Snowflake",
    "ticker": "SNOW",
    "provider_symbol": "SNOW",
    "country": "US",
    "exchange": "NYSE",
    "currency": "USD",
    "sector": "Data Infrastructure",
    "ai_category": "Data and analytics platform",
    "ai_thesis": "Cloud data platform can benefit from AI workloads that require governed enterprise data."
  },
  {
    "name": "Adobe",
    "ticker": "ADBE",
    "provider_symbol": "ADBE",
    "country": "US",
    "exchange": "NASDAQ",
    "currency": "USD",
    "sector": "Creative Software",
    "ai_category": "Enterprise AI software",
    "ai_thesis": "Creative Cloud and Document Cloud integrate generative AI into established professional workflows."
  }
]
```

The loader must enforce required keys, non-empty string values, unique tickers, and unique provider symbols. Tests use small temporary JSON files to verify success and failure paths.

## Task 1: Add Explicit FinImpulse Symbol Lookup

**Files:**
- Modify: `src/investmentagent/fundamentals.py`
- Modify: `tests/test_fundamentals.py`

- [ ] **Step 1: Add failing test for global symbol lookup**

In `tests/test_fundamentals.py`, add a test using the existing FinImpulse fetcher fixture style. The fetcher must assert that the posted search payload contains the exact symbol `"NVDA"` and must return a search payload with one matching item. The test calls:

```python
snapshot = provider.get_fundamentals_for_symbol("NVDA", fallback_currency="USD")
```

Assert:

```python
assert snapshot is not None
assert snapshot.symbol == "NVDA"
assert snapshot.financials.pe_ratio == 31.2
assert snapshot.financials.revenue_eur_m is not None
assert provider.source_check().status == "ok"
assert "Finimpulse lookups parsed" in provider.source_check().detail
```

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_fundamentals.py::test_finimpulse_provider_fetches_explicit_symbol -v
```

Expected result before implementation: the test fails because the provider does not expose `get_fundamentals_for_symbol`.

- [ ] **Step 2: Implement the public provider method**

In `FinimpulseFundamentalsProvider`, add:

```python
def get_fundamentals_for_symbol(
    self, symbol: str, fallback_currency: str | None = None
) -> FundamentalsSnapshot | None:
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol is required")
    return self._get_fundamentals_for_symbol(
        normalized_symbol, fallback_currency=fallback_currency
    )
```

Extract the body of `get_fundamentals()` into a private helper:

```python
def _get_fundamentals_for_symbol(
    self, symbol: str, fallback_currency: str | None
) -> FundamentalsSnapshot | None:
    self.attempted_lookups += 1
    payload = json.dumps({"symbols": [symbol], "quote_types": ["stock"], "limit": 1})
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "Authorization": f"Bearer {self.api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        snapshot = _parse_finimpulse_search_payload(
            payload=self._fetcher(FINIMPULSE_SEARCH_URL, payload, headers),
            symbol=symbol,
            fallback_currency=fallback_currency,
        )
    except Exception as exc:
        self.last_error = _token_safe_error(exc, self.api_key)
        return None
    if snapshot is None:
        return None
    snapshot = self._with_profile(snapshot, headers)
    self._record_valuation_coverage(snapshot)
    self.successful_lookups += 1
    self.last_error = None
    return snapshot
```

Then change `get_fundamentals()` to loop over `finimpulse_symbol_candidates(company)` and return the first non-`None` result from `_get_fundamentals_for_symbol(symbol, company.currency)`.

- [ ] **Step 3: Add USD conversion support**

Extend `_EUR_RATES` with a static USD approximation:

```python
_EUR_RATES = {"EUR": 1.0, "SEK": 0.1, "USD": 0.92}
```

This keeps report scoring deterministic without adding another live FX dependency.

- [ ] **Step 4: Verify fundamentals tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_fundamentals.py -v
```

Expected: all fundamentals tests pass.

## Task 2: Add Global AI Core Module

**Files:**
- Add: `src/investmentagent/data/global_ai_universe.json`
- Add: `src/investmentagent/global_ai.py`
- Add: `tests/test_global_ai.py`

- [ ] **Step 1: Add the universe JSON file**

Create the JSON file from the Curated Universe section. Keep the file under `src/investmentagent/data/` so the existing `pyproject.toml` package-data rule includes it.

- [ ] **Step 2: Add failing universe loader tests**

In `tests/test_global_ai.py`, add tests:

```python
def test_load_global_ai_universe_reads_packaged_entries():
    entries = load_global_ai_universe()

    assert len(entries) >= 10
    assert entries[0].ticker == "NVDA"
    assert entries[0].provider_symbol == "NVDA"
    assert entries[0].ai_category
    assert entries[0].ai_thesis
```

```python
def test_load_global_ai_universe_rejects_missing_required_field(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([{"name": "Broken"}]), encoding="utf-8")

    with pytest.raises(ValueError, match="provider_symbol"):
        load_global_ai_universe(path)
```

```python
def test_load_global_ai_universe_rejects_duplicate_symbols(tmp_path):
    base = valid_universe_entry()
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([base, {**base, "name": "Copy"}]), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate ticker"):
        load_global_ai_universe(path)
```

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_global_ai.py::test_load_global_ai_universe_reads_packaged_entries tests/test_global_ai.py::test_load_global_ai_universe_rejects_missing_required_field tests/test_global_ai.py::test_load_global_ai_universe_rejects_duplicate_symbols -v
```

Expected result before implementation: imports fail because `investmentagent.global_ai` does not exist.

- [ ] **Step 3: Implement universe loading**

Implement:

```python
def load_global_ai_universe(path: Path | None = None) -> tuple[GlobalAIUniverseEntry, ...]:
```

Use `importlib.resources.files("investmentagent").joinpath("data/global_ai_universe.json")` for the packaged path. Parse JSON as a list. For each object, enforce the required string fields from `GlobalAIUniverseEntry`. Normalize `ticker`, `provider_symbol`, `country`, and `currency` to uppercase. Preserve `name`, `exchange`, `sector`, `ai_category`, and `ai_thesis` as cleaned strings. Raise `ValueError` messages that include the missing field name or duplicate identifier.

- [ ] **Step 4: Add scoring tests**

Create helper research objects in `tests/test_global_ai.py` with `CompanyResearch` and `FinancialSnapshot`. Add tests:

```python
def test_score_global_ai_candidate_rewards_quality_growth_and_reasonable_valuation():
    entry = valid_universe_entry(ai_category="Cloud AI platform")
    research = make_research(
        entry,
        pe_ratio=22,
        price_to_book=4.0,
        ev_to_ebit=18,
        revenue_growth_pct=18,
        operating_margin_pct=32,
        debt_to_equity=0.4,
        data_quality=DataQuality.PARTIAL,
    )

    score = score_global_ai_candidate(research, entry)

    assert score.total > 60
    assert score.valuation > 0
    assert score.quality >= 20
    assert score.growth >= 12
    assert "profitable AI-exposed business" in score.reasons
```

```python
def test_score_global_ai_candidate_penalizes_missing_valuation():
    entry = valid_universe_entry()
    research = make_research(
        entry,
        revenue_growth_pct=18,
        operating_margin_pct=24,
        data_quality=DataQuality.THIN,
    )

    score = score_global_ai_candidate(research, entry)

    assert score.data_quality_penalty >= 14
    assert any("missing valuation" in warning for warning in score.warnings)
```

```python
def test_build_global_ai_top5_orders_candidates_by_total_score():
    provider = StaticFundamentalsProvider(
        {
            "CHEAP": snapshot_for(symbol="CHEAP", pe_ratio=18, operating_margin_pct=30, revenue_growth_pct=15),
            "EXPENSIVE": snapshot_for(symbol="EXPENSIVE", pe_ratio=95, operating_margin_pct=20, revenue_growth_pct=35),
            "THIN": snapshot_for(symbol="THIN"),
        }
    )
    entries = (
        valid_universe_entry(name="Cheap Quality", ticker="CHEAP", provider_symbol="CHEAP"),
        valid_universe_entry(name="Expensive Growth", ticker="EXPENSIVE", provider_symbol="EXPENSIVE"),
        valid_universe_entry(name="Thin Data", ticker="THIN", provider_symbol="THIN"),
    )

    report = build_global_ai_top5(provider, entries=entries, limit=2, generated_at="2026-06-08 08:00 EEST")

    assert [item.entry.ticker for item in report.items] == ["CHEAP", "EXPENSIVE"]
    assert report.metadata["report_type"] == "global-ai"
    assert report.metadata["limit"] == 2
```

- [ ] **Step 5: Implement scoring**

Implement `score_global_ai_candidate(research, entry)` with these point buckets:

Valuation, max 30:

- P/E `0 < pe <= 20`: `14`
- P/E `20 < pe <= 35`: `9`
- P/E `35 < pe <= 55`: `4`
- P/E above `55`: no positive P/E points and adds risk warning
- P/B `0 < pb <= 5`: `6`
- P/B `5 < pb <= 10`: `3`
- EV/EBIT `0 < ev <= 20`: `10`
- EV/EBIT `20 < ev <= 35`: `5`
- If no direct valuation fields exist but revenue or net income exists: `5` proxy points

Quality, max 30:

- Operating margin `>= 30`: `18`
- Operating margin `15 to <30`: `13`
- Operating margin `0 to <15`: `7`
- Negative operating margin: `0` and risk warning
- Debt/equity `<= 0.5`: `7`
- Debt/equity `> 0.5 and <= 1.5`: `4`
- Business description present: `5`

Growth, max 20:

- Revenue growth `>= 25`: `20`
- Revenue growth `15 to <25`: `16`
- Revenue growth `5 to <15`: `10`
- Revenue growth `0 to <5`: `5`
- Negative growth: `0` and warning

AI relevance, max 10:

- `AI compute semiconductors`, `AI compute manufacturing`, `Semiconductor equipment`, `Cloud AI platform`: `10`
- `AI infrastructure hardware`, `Model/application platform`, `Data and analytics platform`: `8`
- `Enterprise AI software`: `7`
- Other non-empty category: `5`

Penalties:

- Missing direct valuation fields: `8`
- `DataQuality.PARTIAL`: `4`
- `DataQuality.THIN`: `14`
- P/E above `55`: `12`
- P/B above `10`: `6`
- EV/EBIT above `35`: `8`
- Debt/equity above `1.5`: `8`
- Negative operating margin: `10`

Clamp total to a minimum of `0`. Round all fields to two decimals. Include concise reasons and warnings that render well in Markdown, for example `"profitable AI-exposed business"`, `"reasonable P/E"`, `"strong revenue growth"`, `"missing valuation support"`, and `"valuation risk: high P/E"`.

- [ ] **Step 6: Implement report building**

Implement:

```python
def build_global_ai_top5(
    fundamentals_provider,
    *,
    entries: tuple[GlobalAIUniverseEntry, ...] | None = None,
    limit: int = 5,
    generated_at: str | None = None,
) -> GlobalAIReport:
```

For each entry:

- Build a base `Company` with `ListingSegment.OTHER_PUBLIC`, country, exchange, sector, currency, and AI thesis as `business_description`.
- Call `fundamentals_provider.get_fundamentals_for_symbol(entry.provider_symbol, fallback_currency=entry.currency)`.
- If the provider returns a snapshot, merge market cap, business description, IR URL, financials, and evidence into a `CompanyResearch`.
- If the provider returns `None`, create a `CompanyResearch` with `DataQuality.THIN`, a risk `"missing FinImpulse fundamentals"`, and no evidence.
- Score every candidate.
- Rank by `score.total` descending, then `quality` descending, then `valuation` descending, then ticker ascending.
- Set ranks after truncating to `limit`.
- Include provider `source_check()` when callable. Add one local source check named `"global ai universe"` with status `"ok"` and detail like `"12 curated global AI companies loaded"`.

Implement summary helpers:

- `valuation_summary(research)`: show `P/E`, `P/B`, `EV/EBIT`, or `"No direct valuation multiple available"`.
- `quality_summary(research)`: show operating margin and debt/equity when available.
- `growth_summary(research)`: show revenue growth when available.
- `risk_flags`: combine `research.risks` and `score.warnings`.

- [ ] **Step 7: Verify global AI unit tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_global_ai.py -v
```

Expected: all global AI tests pass.

## Task 3: Add Global AI Renderers

**Files:**
- Modify: `src/investmentagent/renderers.py`
- Modify: `tests/test_global_ai.py`

- [ ] **Step 1: Add failing renderer tests**

In `tests/test_global_ai.py`, add:

```python
def test_render_global_ai_report_markdown_includes_expected_sections():
    report = sample_global_ai_report()

    markdown = render_global_ai_report_markdown(report)

    assert "# InvestmentAgent Global AI Top 5" in markdown
    assert "Research triage only. Not financial advice." in markdown
    assert "## Source Checks" in markdown
    assert "## Top 5 Global AI Candidates" in markdown
    assert "AI compute semiconductors" in markdown
    assert "Valuation:" in markdown
    assert "Quality:" in markdown
    assert "Growth:" in markdown
```

```python
def test_render_global_ai_report_json_contains_ai_fields():
    report = sample_global_ai_report()

    payload = json.loads(render_global_ai_report_json(report))

    assert payload["metadata"]["report_type"] == "global-ai"
    assert payload["items"][0]["ai_category"]
    assert payload["items"][0]["ai_thesis"]
    assert payload["items"][0]["score"]["total"] == report.items[0].score.total
```

- [ ] **Step 2: Implement Markdown renderer**

Add imports for `GlobalAIReport` and `GlobalAIReportItem` inside a type-checking block or use duck typing to avoid circular imports.

Implement:

```python
def render_global_ai_report_markdown(report) -> str:
```

Output shape:

```markdown
# InvestmentAgent Global AI Top 5

> Research triage only. Not financial advice.

_Long-term AI candidates ranked by valuation discipline, quality, growth, AI relevance, and risk._

## Metadata
- generated_at: ...
- report_type: global-ai
- limit: 5
- universe_size: 12

## Source Checks
- global ai universe: ok - 12 curated global AI companies loaded
- finimpulse fundamentals: ok - ...

## Top 5 Global AI Candidates

### #1 NVIDIA (NVDA)
`US` | NASDAQ | `AI compute semiconductors`

**AI thesis:** ...
**Score:** 74
**Valuation:** P/E 31.2; P/B 19.4; EV/EBIT 28.0
**Quality:** Operating margin 54.0%; debt/equity 0.2
**Growth:** Revenue growth 65.0%
**Data quality:** partial

#### Reasons
- ...

#### Risks
- ...

#### Evidence
- [Finimpulse fundamentals lookup (NVDA)](...)
```

If `report.items` is empty, render:

```markdown
_No global AI candidates could be ranked with the current data source._
```

- [ ] **Step 3: Implement JSON renderer**

Implement:

```python
def render_global_ai_report_json(report) -> str:
```

Payload fields:

- `disclaimer`
- `metadata`
- `source_checks`
- `items`

Each item includes:

- `rank`
- `company`
- `ai_category`
- `ai_thesis`
- `financials`
- `score`
- `valuation_summary`
- `quality_summary`
- `growth_summary`
- `risk_flags`
- `evidence`
- `data_quality`

Use existing private helpers `_company_payload`, `_financials_payload`, `_evidence_payload`, `_source_check_payload`, `_normalize_json_value`, and `_stringify`.

- [ ] **Step 4: Verify renderer tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_global_ai.py::test_render_global_ai_report_markdown_includes_expected_sections tests/test_global_ai.py::test_render_global_ai_report_json_contains_ai_fields -v
```

Expected: selected tests pass.

## Task 4: Add CLI Command

**Files:**
- Modify: `src/investmentagent/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add failing CLI tests**

Add tests to `tests/test_cli.py`:

```python
def test_root_command_lists_global_ai_subcommand():
    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "global-ai" in result.output
```

```python
def test_global_ai_top5_requires_finimpulse_key(monkeypatch):
    monkeypatch.delenv("FINIMPULSE_API_KEY", raising=False)

    result = runner.invoke(app, ["global-ai", "top-5"])

    assert result.exit_code != 0
    assert "FINIMPULSE_API_KEY is required" in result.output
```

```python
def test_global_ai_top5_saves_markdown_and_json(monkeypatch):
    class Provider:
        def __init__(self, api_key):
            self.api_key = api_key

        def get_fundamentals_for_symbol(self, symbol, fallback_currency=None):
            return snapshot_for(symbol=symbol, pe_ratio=22, operating_margin_pct=30)

        def source_check(self):
            return SourceCheck("finimpulse fundamentals", "ok", "1/1 Finimpulse lookups parsed")

    monkeypatch.setenv("FINIMPULSE_API_KEY", "secret-token")
    monkeypatch.setattr(cli, "FinimpulseFundamentalsProvider", Provider)

    with isolated_filesystem():
        result = runner.invoke(
            app,
            [
                "global-ai",
                "top-5",
                "--limit",
                "2",
                "--save",
                "reports/global-ai.md",
                "--save",
                "reports/global-ai.json",
                "--generated-at",
                "2026-06-08 08:00 EEST",
            ],
        )
        markdown = Path("reports/global-ai.md").read_text()
        payload = json.loads(Path("reports/global-ai.json").read_text())

    assert result.exit_code == 0
    assert "# InvestmentAgent Global AI Top 5" in result.output
    assert "# InvestmentAgent Global AI Top 5" in markdown
    assert payload["metadata"]["report_type"] == "global-ai"
    assert len(payload["items"]) == 2
```

Add small CLI test helpers for `snapshot_for()` using `FundamentalsSnapshot`, `FinancialSnapshot`, and `Evidence`.

- [ ] **Step 2: Register the Typer sub-app**

In `src/investmentagent/cli.py`:

```python
from investmentagent.global_ai import build_global_ai_top5
from investmentagent.renderers import (
    render_global_ai_report_json,
    render_global_ai_report_markdown,
    ...
)
```

Add:

```python
global_ai_app = typer.Typer(help="Generate global AI investment candidate reports.")
app.add_typer(global_ai_app, name="global-ai")
```

- [ ] **Step 3: Add report save helper**

Add:

```python
def _save_global_ai_report(path: str, report) -> None:
    report_path = Path(path)
    suffix = report_path.suffix.lower()
    if suffix == ".json":
        content = render_global_ai_report_json(report)
    elif suffix in {".md", ".markdown"}:
        content = render_global_ai_report_markdown(report)
    else:
        raise typer.BadParameter("save path must end in .json, .md, or .markdown")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content + "\n", encoding="utf-8")
```

- [ ] **Step 4: Add the command**

Add:

```python
@global_ai_app.command("top-5")
def global_ai_top5(
    limit: int = typer.Option(5, "--limit", min=1, max=20),
    output: str = typer.Option("markdown", "--output", help="Output format: markdown or json."),
    save_paths: list[str] | None = typer.Option(
        None,
        "--save",
        help="Save report to .json, .md, or .markdown. Can be repeated.",
    ),
    generated_at: str | None = typer.Option(
        None,
        "--generated-at",
        help="Display timestamp for the report.",
    ),
) -> None:
```

Inside:

- Normalize `output` to `markdown` or `json`.
- Read `FINIMPULSE_API_KEY` through `_api_key_from_environment`.
- Raise `typer.BadParameter("FINIMPULSE_API_KEY is required for global-ai top-5")` when missing.
- Instantiate `FinimpulseFundamentalsProvider(api_key)`.
- Build the report with `build_global_ai_top5(provider, limit=limit, generated_at=generated_at)`.
- Save every path with `_save_global_ai_report`.
- Print Markdown by default; print JSON when requested.

- [ ] **Step 5: Verify CLI tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_cli.py -v
```

Expected: all CLI tests pass.

## Task 5: Integrate Daily Workflow

**Files:**
- Modify: `.github/workflows/daily-public-watchlist.yml`
- Modify: `tests/test_daily_public_workflow.py`

- [ ] **Step 1: Add failing workflow tests**

Add to `tests/test_daily_public_workflow.py`:

```python
def test_daily_workflow_publishes_global_ai_report_and_links_index():
    workflow = WORKFLOW.read_text()

    assert 'investmentagent global-ai top-5 \\' in workflow
    assert '--save "$REPORT_ROOT/global-ai/${report_date}.md" \\' in workflow
    assert 'cp "$REPORT_ROOT/global-ai/${report_date}.md" "$REPORT_ROOT/global-ai/latest.md"' in workflow
    assert "Top 5 Global AI Candidates" in workflow
    assert "reports/global-ai/latest.html" in workflow
    assert "reports/global-ai/${report_date}.html" in workflow
```

```python
def test_daily_workflow_keeps_global_ai_out_of_performance_update():
    workflow = WORKFLOW.read_text()
    performance_block = workflow[
        workflow.index("investmentagent performance update"):
        workflow.index('          {')
    ]

    assert "global-ai" not in performance_block
```

- [ ] **Step 2: Add workflow generation command**

In the `Generate public watchlist report` shell script, after:

```bash
generate_report "long-term" "long-term"
```

add:

```bash
mkdir -p "$REPORT_ROOT/global-ai"
investmentagent global-ai top-5 \
  --limit 5 \
  --generated-at "$generated_at" \
  --save "$REPORT_ROOT/global-ai/${report_date}.md" \
  > "$RUNNER_TEMP/global-ai-output.txt"
cp "$REPORT_ROOT/global-ai/${report_date}.md" "$REPORT_ROOT/global-ai/latest.md"
```

The command uses the same `FINIMPULSE_API_KEY` environment value as the Nordic reports.

- [ ] **Step 3: Add public index links**

In the `docs/index.md` generation block, add under Today's Reports:

```bash
echo "- [Top 5 Global AI Candidates](reports/global-ai/latest.html)"
```

Add under Dated Reports:

```bash
echo "- [Global AI Top 5 ${report_date}](reports/global-ai/${report_date}.html)"
```

Leave the performance update command unchanged. It must still receive only trading and long-term JSON reports.

- [ ] **Step 4: Verify workflow tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_daily_public_workflow.py -v
```

Expected: workflow tests pass.

## Task 6: Full Verification And Publish

**Files:**
- All modified files from prior tasks.

- [ ] **Step 1: Run targeted feature tests**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest tests/test_global_ai.py tests/test_fundamentals.py tests/test_cli.py tests/test_daily_public_workflow.py -v
```

Expected: all selected tests pass.

- [ ] **Step 2: Run the full suite**

Run:

```bash
/private/tmp/investmentagent-accounting-venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 3: Smoke-test saved global AI report with a test provider path**

Use the CLI tests for deterministic no-network coverage. Do not run a live FinImpulse smoke test unless `FINIMPULSE_API_KEY` is present in the local shell environment. If the key is present, run:

```bash
FINIMPULSE_API_KEY="$FINIMPULSE_API_KEY" investmentagent global-ai top-5 --limit 5 --save /tmp/global-ai-top-5.md
```

Expected: command exits zero, `/tmp/global-ai-top-5.md` contains `# InvestmentAgent Global AI Top 5`, and source checks report FinImpulse coverage.

- [ ] **Step 4: Commit and push directly to main**

From the feature worktree:

```bash
git status --short
git add src/investmentagent/data/global_ai_universe.json src/investmentagent/global_ai.py src/investmentagent/fundamentals.py src/investmentagent/renderers.py src/investmentagent/cli.py .github/workflows/daily-public-watchlist.yml tests/test_global_ai.py tests/test_fundamentals.py tests/test_cli.py tests/test_daily_public_workflow.py
git commit -m "feat: publish global ai top 5 report"
```

Then update main in the primary worktree:

```bash
cd /Users/vernerisirva1/Documents/Investmentagent
git fetch origin main
git pull --ff-only origin main
git merge --ff-only codex/global-ai-top-5
git push origin main
```

If a daily report commit lands on `origin/main` during implementation, rebase `codex/global-ai-top-5` on `origin/main`, rerun the full suite, then fast-forward main and push.

## Acceptance Criteria

- `investmentagent global-ai top-5` prints a Markdown Global AI report by default.
- `investmentagent global-ai top-5 --save docs/reports/global-ai/YYYY-MM-DD.md` writes the standalone report.
- The report includes top five candidates, AI category, AI thesis, valuation summary, quality summary, growth summary, risk flags, evidence, source checks, and disclaimer.
- FinImpulse explicit global symbols work without Nordic suffix inference.
- Missing valuation support lowers score and appears as a visible risk warning.
- `.github/workflows/daily-public-watchlist.yml` publishes `docs/reports/global-ai/YYYY-MM-DD.md` and `docs/reports/global-ai/latest.md`.
- `docs/index.md` links to the latest and dated Global AI report.
- Global AI reports are not passed to `investmentagent performance update`.
- Full pytest suite passes.
