from pathlib import Path


WORKFLOW = Path(".github/workflows/daily-public-watchlist.yml")


def test_scheduled_report_decision_allows_delayed_runs_after_checkout():
    workflow = WORKFLOW.read_text()

    checkout_index = workflow.index("- name: Check out repository")
    decision_index = workflow.index("- name: Decide scheduled run")

    assert checkout_index < decision_index
    assert 'if [ "$helsinki_hour" -lt 8 ]; then' in workflow
    assert '[ -f "$REPORT_ROOT/trading/${report_date}.md" ]' in workflow
