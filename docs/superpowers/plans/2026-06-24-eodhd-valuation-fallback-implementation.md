# EODHD Valuation Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add EODHD as the first real valuation fallback after FinImpulse and before Yahoo.

**Architecture:** Add a provider in `fundamentals.py` that follows the existing provider interface: `get_fundamentals`, `get_fundamentals_for_symbol`, and `source_check`. Wire CLI fallback composition to use EODHD when `EODHD_API_KEY` exists, with Yahoo retained as final fallback diagnostics.

**Tech Stack:** Python 3.11+, Typer, pytest, stdlib `urllib`, existing dataclass models.

---

## File Structure

- Modify `src/investmentagent/fundamentals.py`: add EODHD endpoint constants, symbol candidate mapping, provider class, URL helper, fetch helper, parser, and nested fallback composition helper.
- Modify `src/investmentagent/cli.py`: read `EODHD_API_KEY` and build fallback provider chain for watchlist and Global AI.
- Modify `tests/test_fundamentals.py`: add EODHD payload fixture, provider parsing tests, source-check tests, and fallback-chain tests.
- Modify `tests/test_cli.py`: add watchlist and Global AI wiring tests for EODHD fallback.

## Tasks

### Task 1: Provider Parsing

- [ ] Add an `eodhd_payload()` fixture in `tests/test_fundamentals.py` with `General`, `Highlights`, and `Valuation`.
- [ ] Add a failing test for `EodhdFundamentalsProvider.get_fundamentals_for_symbol("MSFT", fallback_currency="USD")`.
- [ ] Implement EODHD provider URL construction and payload parsing.
- [ ] Verify the focused provider test passes.

### Task 2: Provider Diagnostics

- [ ] Add a failing source-check test requiring valuation coverage details.
- [ ] Add a failing not-configured source-check test.
- [ ] Implement source-check counters and no-key behavior.
- [ ] Verify focused diagnostics tests pass.

### Task 3: Fallback Composition

- [ ] Add tests for a `compose_valuation_fallback_provider` helper that includes EODHD when configured and skips it when not configured.
- [ ] Implement the helper using nested `FallbackFundamentalsProvider` instances.
- [ ] Verify fallback source checks include primary, EODHD, Yahoo, and wrapper checks.

### Task 4: CLI Wiring

- [ ] Add watchlist and Global AI CLI tests that assert `EODHD_API_KEY` causes EODHD to sit between FinImpulse and Yahoo.
- [ ] Wire `EODHD_API_KEY` into CLI provider construction.
- [ ] Verify CLI tests pass.

### Task 5: Full Verification And Publish

- [ ] Run targeted tests: `pytest tests/test_fundamentals.py tests/test_cli.py tests/test_global_ai.py -v`.
- [ ] Run full suite: `pytest`.
- [ ] Commit with `feat: add eodhd valuation fallback`.
- [ ] Fast-forward `main`, rerun full suite, push `main` and `codex/investmentagent-live-data`.
