# Public Idea Reports And Company Descriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish readable daily top-10 trading and long-term idea reports with real company business descriptions.

**Architecture:** Extend the source-agnostic `Company` model with an optional `business_description`, enrich it through Finimpulse profile calls, render saved Markdown reports with proper Markdown sections, and update the GitHub Actions workflow to generate two strategy-specific public reports.

**Tech Stack:** Python dataclasses, Typer CLI, existing InvestmentAgent renderer/provider architecture, GitHub Actions, GitHub Pages Markdown.

---

## File Structure

- Modify `src/investmentagent/models.py`: add optional `Company.business_description`.
- Modify `src/investmentagent/fundamentals.py`: add Finimpulse profile endpoint support and carry profile description in `FundamentalsSnapshot`.
- Modify `src/investmentagent/renderers.py`: render structured Markdown reports and use business descriptions when available.
- Modify `.github/workflows/daily-public-watchlist.yml`: generate trading and long-term reports.
- Modify tests in `tests/test_fundamentals.py` and `tests/test_reports.py`.
- Update `README.md` with the two public report links.

## Task 1: Company Description Enrichment

- [ ] Add failing tests showing Finimpulse profile `long_business_summary` becomes `Company.business_description`.
- [ ] Implement `Company.business_description` and Finimpulse profile parsing.
- [ ] Keep profile failures best-effort and token-safe.
- [ ] Run focused fundamentals tests and commit.

## Task 2: Readable Markdown Reports

- [ ] Add failing tests for structured Markdown report output.
- [ ] Render saved Markdown reports with headings, sections, and bullets.
- [ ] Use `Company.business_description` for "What the company does"; fall back to the generated presentation.
- [ ] Run focused report tests and commit.

## Task 3: Public Workflow Split

- [ ] Update the workflow to generate `docs/reports/trading/YYYY-MM-DD.md` and `docs/reports/long-term/YYYY-MM-DD.md`.
- [ ] Update `docs/index.md` and `README.md` links.
- [ ] Run full tests plus `git diff --check`.
- [ ] Commit and push directly to GitHub.
