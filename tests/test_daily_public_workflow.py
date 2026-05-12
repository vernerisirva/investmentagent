from pathlib import Path


WORKFLOW = Path(".github/workflows/daily-public-watchlist.yml")
PAGES_WORKFLOW = Path(".github/workflows/pages.yml")


def test_scheduled_report_decision_allows_delayed_runs_after_checkout():
    workflow = WORKFLOW.read_text()

    checkout_index = workflow.index("- name: Check out repository")
    decision_index = workflow.index("- name: Decide scheduled run")

    assert checkout_index < decision_index
    assert 'if [ "$helsinki_hour" -lt 8 ]; then' in workflow
    assert '[ -f "$REPORT_ROOT/trading/${report_date}.md" ]' in workflow


def test_pages_deploy_workflow_uses_node24_compatible_actions():
    workflow = PAGES_WORKFLOW.read_text()

    assert "actions/checkout@v6" in workflow
    assert "actions/upload-pages-artifact@v5" in workflow
    assert "actions/deploy-pages@v5" in workflow
    assert "actions/checkout@v4" not in workflow
    assert "actions/upload-artifact@v4" not in workflow
