# Public Daily Watchlist Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add public weekday publishing for InvestmentAgent watchlist reports through GitHub Actions and GitHub Pages.

**Architecture:** A scheduled GitHub Actions workflow generates Markdown reports into `docs/reports/` and commits them to `main`. GitHub Pages serves the `docs/` folder, with `docs/index.md` linking to the latest and historical report files.

**Tech Stack:** GitHub Actions, Python 3.12, the existing `investmentagent` CLI, GitHub Pages Markdown rendering.

---

## File Structure

- Create `.github/workflows/daily-public-watchlist.yml`: scheduled and manual workflow that generates, commits, and pushes public report files.
- Create `docs/index.md`: initial public landing page with setup-safe content.
- Create `docs/reports/.gitkeep`: keeps the report directory in git until the first generated report.
- Modify `README.md`: document GitHub secret setup, Pages setup, and the public publishing workflow.

## Task 1: Add Public Publishing Workflow

**Files:**
- Create: `.github/workflows/daily-public-watchlist.yml`
- Create: `docs/index.md`
- Create: `docs/reports/.gitkeep`
- Modify: `README.md`

- [ ] **Step 1: Create the workflow**

Add a workflow that:

- Runs at 05:00 and 06:00 UTC Monday-Friday.
- Skips scheduled duplicate runs unless the current Helsinki hour is `08`.
- Supports manual `workflow_dispatch`.
- Requires `FINIMPULSE_API_KEY`.
- Installs the package with `python -m pip install -e .`.
- Runs `investmentagent watchlist --provider live --fundamentals finimpulse --country se,fi --limit 25 --strategy balanced --verbose --save docs/reports/YYYY-MM-DD.md`.
- Copies the dated report to `docs/reports/latest.md`.
- Rewrites `docs/index.md` with links to the latest report and report archive.
- Commits generated docs only when changed.

- [ ] **Step 2: Add the initial public landing page**

Create `docs/index.md` with a short public landing page that links to `reports/latest.md` and explains that reports will appear after the first scheduled or manual workflow run.

- [ ] **Step 3: Document setup**

Update `README.md` with:

- GitHub secret name: `FINIMPULSE_API_KEY`.
- GitHub Pages source: branch `main`, folder `/docs`.
- Workflow name and manual run path.
- Public report URL pattern.
- Reminder that reports are research triage only and not financial advice.

- [ ] **Step 4: Verify locally**

Run:

```bash
/Users/vernerisirva/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest
```

Expected: all tests pass.

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 5: Commit and push**

Commit the workflow and docs, then push `main` directly to GitHub.
