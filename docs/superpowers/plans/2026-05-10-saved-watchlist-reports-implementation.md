# Saved Watchlist Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--save PATH` to `investmentagent watchlist` so users can persist JSON or Markdown daily watchlist snapshots.

**Architecture:** Add report-file rendering helpers in `src/investmentagent/renderers.py` and keep CLI file-writing orchestration in `src/investmentagent/cli.py`. Tests use Typer's isolated filesystem so no public internet or user directories are touched.

**Tech Stack:** Python 3.12, Typer, pytest, JSON and Markdown text output.

---

### Task 1: Saved JSON Report

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/investmentagent/cli.py`
- Modify: `src/investmentagent/renderers.py`

- [ ] **Step 1: Write failing JSON save test**

Add a CLI test that invokes:

```python
result = runner.invoke(
    app,
    ["watchlist", "--limit", "1", "--save", "reports/watchlist.json"],
)
```

Assert exit code `0`, file exists, and parsed JSON includes `metadata`, `source_checks`, and `items`.

- [ ] **Step 2: Run focused test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli.py::test_watchlist_saves_json_report -v
```

Expected: FAIL because `--save` does not exist.

- [ ] **Step 3: Implement JSON save**

Add `save_path: str | None = typer.Option(None, "--save", help="Save report to .json, .md, or .markdown.")` to `watchlist`.

Add a report renderer that produces JSON with:

```python
{
  "metadata": {
    "generated_at": "...",
    "provider": "fixture",
    "countries": ["SE", "FI"],
    "limit": 1,
    "include_first_north": True,
    "min_market_cap": None,
    "max_market_cap": None,
    "sector": None
  },
  "source_checks": [...],
  "items": [...]
}
```

Write the file after building the watchlist and before returning console output.

- [ ] **Step 4: Verify JSON save**

Run the focused test from Step 2. Expected: PASS.

### Task 2: Markdown Report And Validation

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/investmentagent/cli.py`
- Modify: `src/investmentagent/renderers.py`

- [ ] **Step 1: Write failing Markdown and invalid-extension tests**

Add tests:

```python
def test_watchlist_saves_markdown_report():
    result = runner.invoke(app, ["watchlist", "--limit", "1", "--save", "reports/watchlist.md"])
    assert result.exit_code == 0
    content = Path("reports/watchlist.md").read_text()
    assert "# InvestmentAgent Watchlist" in content
    assert "## Metadata" in content
    assert "## Watchlist" in content


def test_watchlist_rejects_unsupported_save_extension():
    result = runner.invoke(app, ["watchlist", "--limit", "1", "--save", "reports/watchlist.txt"])
    assert result.exit_code != 0
    assert "save path must end in .json, .md, or .markdown" in result.output
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli.py::test_watchlist_saves_markdown_report tests/test_cli.py::test_watchlist_rejects_unsupported_save_extension -v
```

Expected: FAIL because Markdown save and extension validation do not exist.

- [ ] **Step 3: Implement Markdown and validation**

Add helper logic to choose `.json`, `.md`, or `.markdown`; raise `typer.BadParameter` for other extensions. Add Markdown output with title, metadata, source checks, and the existing watchlist text body.

- [ ] **Step 4: Run CLI tests**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli.py -v
```

Expected: PASS.

### Task 3: Verification And Commit

**Files:**
- No additional source changes expected.

- [ ] **Step 1: Run full suite**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q
```

Expected: PASS.

- [ ] **Step 2: Run real CLI save smoke test**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/investmentagent watchlist --provider fixture --country se,fi --limit 2 --save /private/tmp/investmentagent-watchlist.md
```

Expected: command exits `0` and `/private/tmp/investmentagent-watchlist.md` exists.

- [ ] **Step 3: Commit**

Run:

```bash
git add src/investmentagent/cli.py src/investmentagent/renderers.py tests/test_cli.py docs/superpowers/plans/2026-05-10-saved-watchlist-reports-implementation.md
git commit -m "feat: save watchlist reports"
```
