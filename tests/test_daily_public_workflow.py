import subprocess
from pathlib import Path

import pytest


WORKFLOW = Path(".github/workflows/daily-public-watchlist.yml")
PAGES_WORKFLOW = Path(".github/workflows/pages.yml")
PUBLISH_SCRIPT = Path(".github/scripts/publish-staged.sh")


def test_scheduled_report_decision_allows_delayed_runs_after_checkout():
    workflow = WORKFLOW.read_text()

    checkout_index = workflow.index("- name: Check out repository")
    decision_index = workflow.index("- name: Decide scheduled run")
    install_index = workflow.index("- name: Install InvestmentAgent")
    market_index = workflow.index("- name: Skip closed Nordic market days")
    generate_index = workflow.index("- name: Generate public watchlist report")
    wait_index = workflow.index('sleep "$wait_seconds"')
    duplicate_check_index = workflow.index('[ -f "$REPORT_ROOT/trading/${report_date}.md" ]')

    assert checkout_index < decision_index
    assert install_index < market_index < generate_index
    assert wait_index < duplicate_check_index
    assert "timeout-minutes: 390" in workflow
    assert 'cron: "7,17,27,37,47,57 0-7 * * 1-5"' in workflow
    assert 'if [ "$helsinki_hour" -lt 8 ]; then' in workflow
    assert 'helsinki_minute="$(TZ=Europe/Helsinki date +%M)"' in workflow
    assert "wait_seconds=$(( (8 - 10#$helsinki_hour) * 3600 - 10#$helsinki_minute * 60 ))" in workflow
    assert '[ -f "$REPORT_ROOT/trading/${report_date}.md" ]' in workflow
    assert "investmentagent markets open" in workflow
    assert '--market stockholm \\' in workflow
    assert '--market helsinki' in workflow


def test_scheduled_report_decision_requires_all_daily_report_types_before_skipping():
    workflow = WORKFLOW.read_text()
    decision_block = workflow[
        workflow.index("- name: Decide scheduled run"):
        workflow.index("- name: Set up Python")
    ]

    assert '[ -f "$REPORT_ROOT/trading/${report_date}.md" ]' in decision_block
    assert '[ -f "$REPORT_ROOT/long-term/${report_date}.md" ]' in decision_block
    assert '[ -f "$REPORT_ROOT/global-ai/${report_date}.md" ]' in decision_block


def test_report_commit_keeps_scheduler_branch_in_sync():
    workflow = WORKFLOW.read_text()
    publisher = PUBLISH_SCRIPT.read_text()

    assert "git push origin HEAD:main" in publisher
    assert "git push origin HEAD:codex/investmentagent-live-data" in publisher
    assert workflow.count("bash .github/scripts/publish-staged.sh") == 2


def test_daily_watchlists_use_explicit_broader_enrichment_budget():
    workflow = WORKFLOW.read_text()

    assert "--limit 10" in workflow
    assert "--refresh-limit 30" in workflow


def test_daily_workflow_reuses_a_private_fundamentals_cache():
    workflow = WORKFLOW.read_text()

    assert "uses: actions/cache/restore@v5" in workflow
    assert "uses: actions/cache/save@v5" in workflow
    assert "uses: actions/cache@v5" not in workflow
    assert "path: .investmentagent/fundamentals-cache.json" in workflow
    assert "--fundamentals-cache .investmentagent/fundamentals-cache.json" in workflow
    assert "--cache-max-age-days 45" in workflow
    assert "git add .investmentagent" not in workflow


def test_daily_workflow_persists_full_universe_evaluations_from_report_runs():
    workflow = WORKFLOW.read_text()

    assert "EVALUATION_ROOT: data/evaluations" in workflow
    assert '--evaluation-dir "$EVALUATION_ROOT"' in workflow
    assert '--evaluation-report-date "$report_date"' in workflow
    assert 'git add docs/index.md docs/global-ai.md "$REPORT_ROOT"' in workflow
    assert '"$EVALUATION_ROOT"' in workflow
    assert "git add .investmentagent" not in workflow


def test_daily_workflow_records_long_term_shadow_experiment_without_another_refresh():
    workflow = WORKFLOW.read_text()

    assert "EXPERIMENT_ROOT: data/evaluation-experiments" in workflow
    generation_block = workflow[
        workflow.index("generate_report() {"):
        workflow.index('generate_report "trading" "trading"')
    ]
    assert 'if [ "$strategy" = "long-term" ]; then' in generation_block
    assert 'experiment_args=(--experiment-dir "$EXPERIMENT_ROOT")' in generation_block
    assert '"${experiment_args[@]}" \\' in generation_block
    assert generation_block.count("--refresh-limit 30") == 1
    assert '--experiment-root "$EXPERIMENT_ROOT"' in workflow
    assert 'git add "$EXPERIMENT_ROOT"' in workflow


def test_daily_workflow_refreshes_performance_v2_without_blocking_publication():
    workflow = WORKFLOW.read_text()

    assert "OUTCOME_ROOT: data/evaluation-outcomes" in workflow
    assert "ANALYSIS_ROOT: data/evaluation-analysis" in workflow
    assert "- name: Refresh Performance v2 outcomes" in workflow
    performance_v2_block = workflow[
        workflow.index("- name: Refresh Performance v2 outcomes"):
        workflow.index("- name: Commit performance records")
    ]
    for step in ("- name: Refresh Performance v2 outcomes", "- name: Analyze Performance v2"):
        block = performance_v2_block[performance_v2_block.index(step):]
        block = block[:block.index("\n      - name:", 1) if "\n      - name:" in block[1:] else len(block)]
        assert "continue-on-error: true" in block and "timeout-minutes: 45" in block
    assert "EODHD_API_KEY: ${{ secrets.EODHD_API_KEY }}" in performance_v2_block
    assert "investmentagent evaluate outcomes" in performance_v2_block
    assert "investmentagent evaluate analyze" in performance_v2_block
    assert "Skipping Performance v2 outcome refresh" in performance_v2_block
    assert "Restore market-price histories" in workflow
    assert ".investmentagent/market-price-cache.histories-v2.json" in workflow
    assert "--return-methodology single-response-adjusted-close-v1" in performance_v2_block
    assert '--data-cutoff "$analysis_at"' in performance_v2_block
    assert "--reprice" not in performance_v2_block
    assert "market-prices-${{ runner.os }}-" in workflow
    assert "--price-cache .investmentagent/market-price-cache.json" in performance_v2_block
    assert "--max-price-api-calls 20" in performance_v2_block
    assert 'git add "$OUTCOME_ROOT"' in workflow
    assert 'git add "$ANALYSIS_ROOT"' in workflow
    assert "git add .investmentagent" not in workflow


def test_daily_workflow_publishes_global_ai_report_and_links_index():
    workflow = WORKFLOW.read_text()

    assert 'investmentagent global-ai top-5 \\' in workflow
    assert '--save "$REPORT_ROOT/global-ai/${report_date}.md" \\' in workflow
    assert (
        'cp "$REPORT_ROOT/global-ai/${report_date}.md" '
        '"$REPORT_ROOT/global-ai/latest.md"'
    ) in workflow
    assert "## Global AI" in workflow
    assert "global-ai.html" in workflow
    assert "Top 5 Global AI Candidates" in workflow
    assert "reports/global-ai/latest.html" in workflow
    assert "reports/global-ai/${report_date}.html" in workflow


def test_daily_workflow_writes_global_ai_landing_page():
    workflow = WORKFLOW.read_text()

    assert "# InvestmentAgent Global AI" in workflow
    assert "> docs/global-ai.md" in workflow
    assert "reports/global-ai/latest.html" in workflow
    assert "reports/global-ai/${report_date}.html" in workflow
    assert "git add docs/index.md docs/global-ai.md" in workflow


def test_daily_workflow_keeps_global_ai_out_of_performance_update():
    workflow = WORKFLOW.read_text()
    performance_block = workflow[
        workflow.index("investmentagent performance update"):
        workflow.index("- name: Refresh Performance v2 outcomes")
    ]

    assert "--report-json" in performance_block
    assert "global-ai" not in performance_block


def test_pages_deploy_workflow_uses_node24_compatible_actions():
    workflow = PAGES_WORKFLOW.read_text()

    assert "actions/checkout@v6" in workflow
    assert "actions/upload-pages-artifact@v5" in workflow
    assert "actions/deploy-pages@v5" in workflow
    assert "actions/checkout@v4" not in workflow
    assert "actions/upload-artifact@v4" not in workflow


def test_decision_time_evidence_is_published_before_any_derived_record():
    workflow = WORKFLOW.read_text()
    order = [workflow.index(f"- name: {name}") for name in (
        "Generate public watchlist report", "Commit public report", "Update legacy performance scorecard",
        "Refresh Performance v2 outcomes", "Analyze Performance v2", "Commit performance records")]
    assert order == sorted(order)
    generate = workflow[order[0]:order[1]]
    evidence = workflow[order[1]:order[2]]
    records = workflow[order[5]:]
    assert "investmentagent performance update" not in generate
    assert 'echo "REPORT_DATE=${report_date}" >> "$GITHUB_ENV"' in generate
    assert '"$EVALUATION_ROOT"' in evidence and 'git add "$EXPERIMENT_ROOT"' in evidence
    for derived in ("$OUTCOME_ROOT", "$ANALYSIS_ROOT", "docs/performance", "docs/data/performance"):
        assert derived not in evidence
    assert 'publish-staged.sh "reports: publish daily watchlist ${REPORT_DATE}"' in evidence
    assert 'git add "$OUTCOME_ROOT"' in records
    analysis_gate = records.index('if [ "${{ steps.performance_v2_analysis.outcome }}" = "success" ]; then')
    assert analysis_gate < records.index('git add "$ANALYSIS_ROOT"')
    assert 'publish-staged.sh "reports: update performance records ${REPORT_DATE}"' in records


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def publish_repo(tmp_path):
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    _git(work, "config", "user.name", "test")
    _git(work, "config", "user.email", "test@example.invalid")
    (work / "seed.txt").write_text("seed\n")
    _git(work, "add", "seed.txt")
    _git(work, "commit", "-q", "-m", "seed")
    _git(work, "remote", "add", "origin", str(remote))
    return work, remote


def _publish(work):
    return subprocess.run(["bash", str(PUBLISH_SCRIPT.resolve()), "reports: test"], cwd=work,
                          capture_output=True, text=True)


def _sparse(path, size):
    with path.open("wb") as handle:
        handle.truncate(size)


def test_publisher_pushes_staged_files_to_main_and_scheduler_branch(publish_repo):
    work, remote = publish_repo
    (work / "x.json").write_text("{}\n")
    _git(work, "add", "x.json")
    result = _publish(work)
    assert result.returncode == 0, result.stdout + result.stderr
    head = _git(work, "rev-parse", "HEAD")
    assert _git(remote, "rev-parse", "main") == _git(remote, "rev-parse", "codex/investmentagent-live-data") == head


def test_publisher_without_staged_changes_creates_no_commit(publish_repo):
    work, _ = publish_repo
    before = _git(work, "rev-parse", "HEAD")
    result = _publish(work)
    assert result.returncode == 0 and "No changes to commit" in result.stdout
    assert _git(work, "rev-parse", "HEAD") == before


def test_publisher_refuses_a_file_github_would_reject(publish_repo):
    work, remote = publish_repo
    _sparse(work / "analysis.json", 100 * 1024 * 1024 + 1)
    _git(work, "add", "analysis.json")
    before = _git(work, "rev-parse", "HEAD")
    result = _publish(work)
    assert result.returncode == 1
    assert "::error file=analysis.json::" in result.stdout
    assert _git(work, "rev-parse", "HEAD") == before
    assert subprocess.run(["git", "rev-parse", "--verify", "-q", "main"], cwd=remote,
                          capture_output=True).returncode != 0


def test_publisher_warns_above_the_recommended_size_but_publishes(publish_repo):
    work, remote = publish_repo
    _sparse(work / "ledger.json", 50 * 1024 * 1024 + 1)
    _git(work, "add", "ledger.json")
    result = _publish(work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning file=ledger.json::" in result.stdout
    assert _git(remote, "rev-parse", "main") == _git(work, "rev-parse", "HEAD")


def _step(workflow, name):
    start = workflow.index(f"- name: {name}")
    end = workflow.find("\n      - name:", start + 1)
    return workflow[start:] if end == -1 else workflow[start:end]


def test_caches_are_saved_even_when_a_later_step_fails():
    workflow = WORKFLOW.read_text()
    order = [workflow.index(f"- name: {name}") for name in (
        "Restore private fundamentals cache", "Generate public watchlist report", "Save private fundamentals cache",
        "Commit public report", "Refresh Performance v2 outcomes", "Save market-price histories",
        "Analyze Performance v2", "Commit performance records")]
    assert order == sorted(order)
    for restore, save, cache_id in (
            ("Restore private fundamentals cache", "Save private fundamentals cache", "fundamentals_cache"),
            ("Restore market-price histories", "Save market-price histories", "price_cache")):
        restore_step, save_step = _step(workflow, restore), _step(workflow, save)
        assert f"id: {cache_id}" in restore_step and "uses: actions/cache/restore@v5" in restore_step
        assert f"if: always() && steps.{cache_id}.outcome == 'success'" in save_step
        assert "continue-on-error: true" in save_step and "uses: actions/cache/save@v5" in save_step
        assert f"key: ${{{{ steps.{cache_id}.outputs.cache-primary-key }}}}" in save_step
        paths = restore_step[restore_step.index("path:"):restore_step.index("key:")]
        assert paths in save_step


def test_degraded_performance_records_fail_the_run_after_publication():
    workflow = WORKFLOW.read_text()
    alert = _step(workflow, "Report degraded performance records")
    assert workflow.index("- name: Commit performance records") < workflow.index("- name: Report degraded performance records")
    assert "steps.performance_v2_outcomes.outcome == 'failure'" in alert
    assert "steps.performance_v2_analysis.outcome == 'failure'" in alert
    assert "exit 1" in alert and "always()" not in alert
    assert "id: performance_v2_outcomes" in _step(workflow, "Refresh Performance v2 outcomes")
    assert "id: performance_v2_analysis" in _step(workflow, "Analyze Performance v2")
