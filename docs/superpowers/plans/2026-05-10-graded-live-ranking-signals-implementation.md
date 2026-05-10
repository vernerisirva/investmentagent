# Graded Live Ranking Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve live watchlist ordering by turning Nasdaq intraday change and turnover into graded catalysts and risks.

**Architecture:** Keep the logic in `src/investmentagent/providers.py` where Nasdaq rows are already converted into live `CompanyResearch`. The existing scoring engine will rank stronger live signals higher through its catalyst scoring.

**Tech Stack:** Python 3.12, pytest, existing provider/scoring/report dataclasses.

---

### Task 1: Graded Catalyst Labels

**Files:**
- Modify: `tests/test_providers.py`
- Modify: `src/investmentagent/providers.py`

- [ ] **Step 1: Write failing provider tests**

Add tests proving `+12.93%` creates `Strong intraday momentum (+12.93%)`, `+6.25%` creates `Positive intraday momentum (+6.25%)`, and high turnover creates `High live turnover`.

- [ ] **Step 2: Run focused tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_providers.py::test_live_provider_research_adds_positive_momentum_signal tests/test_providers.py::test_live_provider_research_adds_strong_momentum_and_high_turnover_signals -v
```

Expected: FAIL because current labels are not graded and no high-turnover catalyst exists.

- [ ] **Step 3: Implement graded signal helpers**

Update `_live_market_catalysts()` to add:

```python
if percentage_change >= 10:
    catalysts.append(f"Strong intraday momentum (+{percentage_change:g}%)")
elif percentage_change >= 5:
    catalysts.append(f"Positive intraday momentum (+{percentage_change:g}%)")
if turnover >= 1_000_000:
    catalysts.append("High live turnover")
elif turnover >= 250_000:
    catalysts.append("Moderate live turnover")
```

- [ ] **Step 4: Verify focused tests pass**

Run the focused command from Step 2. Expected: PASS.

### Task 2: Ranking Difference

**Files:**
- Modify: `tests/test_reports.py` or `tests/test_providers.py`
- Modify: `src/investmentagent/providers.py` only if Task 1 did not complete the behavior.

- [ ] **Step 1: Write ranking test**

Add a test using two live rows where one has stronger signal count than the other, then assert `score_research(stronger).total > score_research(weaker).total`.

- [ ] **Step 2: Run focused test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_providers.py::test_live_provider_scores_stronger_live_signals_higher -v
```

Expected: PASS after Task 1, or FAIL if more implementation is needed.

- [ ] **Step 3: Run full suite**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q
```

Expected: PASS.

### Task 3: Live CLI Verification And Commit

**Files:**
- No additional source changes expected.

- [ ] **Step 1: Run live watchlist smoke test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent watchlist --provider live --country se,fi --limit 10
```

Expected: output shows graded reasons such as `Strong intraday momentum` or `High live turnover`.

- [ ] **Step 2: Commit**

Run:

```bash
git add src/investmentagent/providers.py tests/test_providers.py docs/superpowers/plans/2026-05-10-graded-live-ranking-signals-implementation.md
git commit -m "feat: grade live ranking signals"
```
