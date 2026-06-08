from pathlib import Path


WORKFLOW = Path(".github/workflows/daily-public-watchlist.yml")
PAGES_WORKFLOW = Path(".github/workflows/pages.yml")


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


def test_report_commit_keeps_scheduler_branch_in_sync():
    workflow = WORKFLOW.read_text()

    assert "git push origin HEAD:main" in workflow
    assert "git push origin HEAD:codex/investmentagent-live-data" in workflow


def test_daily_workflow_publishes_global_ai_report_and_links_index():
    workflow = WORKFLOW.read_text()

    assert 'investmentagent global-ai top-5 \\' in workflow
    assert '--save "$REPORT_ROOT/global-ai/${report_date}.md" \\' in workflow
    assert (
        'cp "$REPORT_ROOT/global-ai/${report_date}.md" '
        '"$REPORT_ROOT/global-ai/latest.md"'
    ) in workflow
    assert "Top 5 Global AI Candidates" in workflow
    assert "reports/global-ai/latest.html" in workflow
    assert "reports/global-ai/${report_date}.html" in workflow


def test_daily_workflow_keeps_global_ai_out_of_performance_update():
    workflow = WORKFLOW.read_text()
    performance_block = workflow[
        workflow.index("investmentagent performance update"):
        workflow.index('          {')
    ]

    assert "global-ai" not in performance_block


def test_pages_deploy_workflow_uses_node24_compatible_actions():
    workflow = PAGES_WORKFLOW.read_text()

    assert "actions/checkout@v6" in workflow
    assert "actions/upload-pages-artifact@v5" in workflow
    assert "actions/deploy-pages@v5" in workflow
    assert "actions/checkout@v4" not in workflow
    assert "actions/upload-artifact@v4" not in workflow
