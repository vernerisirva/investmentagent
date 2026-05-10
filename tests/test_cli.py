import json
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

import investmentagent.cli as cli
from investmentagent.cli import app
from investmentagent.models import SourceCheck


runner = CliRunner()


def test_console_script_target_exposes_app():
    assert app is not None


def test_module_invocation_renders_help():
    result = subprocess.run(
        [sys.executable, "-m", "investmentagent.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "watchlist" in result.stdout


def test_root_command_without_args_shows_help():
    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "watchlist" in result.output
    assert "deep-dive" in result.output
    assert "sources" in result.output


def test_watchlist_command_outputs_ranked_text():
    result = runner.invoke(app, ["watchlist", "--country", "se,fi", "--limit", "2"])

    assert result.exit_code == 0
    assert "#1" in result.output
    assert "Not financial advice" in result.output


def test_watchlist_command_outputs_json():
    result = runner.invoke(
        app, ["watchlist", "--country", "se,fi", "--limit", "1", "--output", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["items"][0]["rank"] == 1
    assert "disclaimer" in payload


def test_watchlist_accepts_fixture_provider_option():
    result = runner.invoke(app, ["watchlist", "--provider", "fixture", "--limit", "1"])

    assert result.exit_code == 0
    assert "#1" in result.output


def test_watchlist_saves_json_report():
    with runner.isolated_filesystem():
        result = runner.invoke(
            app,
            ["watchlist", "--limit", "1", "--save", "reports/watchlist.json"],
        )

        report_path = Path("reports/watchlist.json")
        payload = json.loads(report_path.read_text())

    assert result.exit_code == 0
    assert "#1" in result.output
    assert payload["metadata"]["provider"] == "fixture"
    assert payload["metadata"]["countries"] == ["SE", "FI"]
    assert payload["source_checks"][0]["name"] == "bundled seed data"
    assert payload["items"][0]["rank"] == 1


def test_watchlist_saves_markdown_report():
    with runner.isolated_filesystem():
        result = runner.invoke(
            app,
            ["watchlist", "--limit", "1", "--save", "reports/watchlist.md"],
        )

        content = Path("reports/watchlist.md").read_text()

    assert result.exit_code == 0
    assert "# InvestmentAgent Watchlist" in content
    assert "## Metadata" in content
    assert "## Source Checks" in content
    assert "## Watchlist" in content


def test_watchlist_rejects_unsupported_save_extension():
    result = runner.invoke(app, ["watchlist", "--limit", "1", "--save", "reports/watchlist.txt"])

    assert result.exit_code != 0
    assert "save path must end in .json, .md, or .markdown" in result.output


def test_watchlist_accepts_strategy_option():
    result = runner.invoke(app, ["watchlist", "--strategy", "long-term", "--limit", "1"])

    assert result.exit_code == 0
    assert "#1" in result.output


def test_watchlist_accepts_fundamentals_option():
    result = runner.invoke(
        app, ["watchlist", "--provider", "fixture", "--fundamentals", "off", "--limit", "1"]
    )

    assert result.exit_code == 0
    assert "#1" in result.output


def test_watchlist_auto_fundamentals_wraps_live_provider(monkeypatch):
    wrapped = {}

    class LiveProvider:
        def list_companies(self, countries, include_first_north):
            return []

        def source_checks(self):
            return [SourceCheck("nasdaq nordic live data", "ok", "live data available")]

    class FundamentalsProvider:
        pass

    class EnrichedProvider:
        def __init__(self, base_provider, fundamentals_provider):
            wrapped["base_provider"] = base_provider
            wrapped["fundamentals_provider"] = fundamentals_provider
            self.base_provider = base_provider

        def list_companies(self, countries, include_first_north):
            return self.base_provider.list_companies(countries, include_first_north)

        def source_checks(self):
            return self.base_provider.source_checks()

    monkeypatch.setattr(cli, "create_provider", lambda name: LiveProvider())
    monkeypatch.setattr(cli, "YahooFundamentalsProvider", FundamentalsProvider, raising=False)
    monkeypatch.setattr(cli, "EnrichedResearchProvider", EnrichedProvider, raising=False)

    result = runner.invoke(app, ["watchlist", "--provider", "live"])

    assert result.exit_code == 0
    assert isinstance(wrapped["base_provider"], LiveProvider)
    assert isinstance(wrapped["fundamentals_provider"], FundamentalsProvider)


def test_watchlist_rejects_invalid_strategy_before_provider_work(monkeypatch):
    def fail_if_called(name: str):
        raise AssertionError("provider should not be created for invalid strategy")

    monkeypatch.setattr(cli, "create_provider", fail_if_called)

    result = runner.invoke(app, ["watchlist", "--provider", "live", "--strategy", "bad"])

    assert result.exit_code != 0
    assert "strategy must be one of" in result.output


def test_watchlist_rejects_invalid_fundamentals_before_provider_work(monkeypatch):
    def fail_if_called(name: str):
        raise AssertionError("provider should not be created for invalid fundamentals mode")

    monkeypatch.setattr(cli, "create_provider", fail_if_called)

    result = runner.invoke(app, ["watchlist", "--provider", "live", "--fundamentals", "bad"])

    assert result.exit_code != 0
    assert "fundamentals must be 'auto', 'off', or 'free'" in result.output


def test_watchlist_saves_strategy_metadata():
    with runner.isolated_filesystem():
        result = runner.invoke(
            app,
            [
                "watchlist",
                "--strategy",
                "trading",
                "--limit",
                "1",
                "--save",
                "reports/watchlist.json",
            ],
        )

        payload = json.loads(Path("reports/watchlist.json").read_text())

    assert result.exit_code == 0
    assert payload["metadata"]["strategy"] == "trading"


def test_watchlist_saves_fundamentals_metadata():
    with runner.isolated_filesystem():
        result = runner.invoke(
            app,
            [
                "watchlist",
                "--provider",
                "fixture",
                "--fundamentals",
                "off",
                "--limit",
                "1",
                "--save",
                "reports/watchlist.json",
            ],
        )

        payload = json.loads(Path("reports/watchlist.json").read_text())

    assert result.exit_code == 0
    assert payload["metadata"]["fundamentals"] == "off"


def test_watchlist_saves_effective_fixture_fundamentals_metadata_by_default():
    with runner.isolated_filesystem():
        result = runner.invoke(
            app,
            [
                "watchlist",
                "--provider",
                "fixture",
                "--limit",
                "1",
                "--save",
                "reports/watchlist.json",
            ],
        )

        payload = json.loads(Path("reports/watchlist.json").read_text())

    assert result.exit_code == 0
    assert payload["metadata"]["fundamentals"] == "off"


def test_watchlist_saves_effective_fixture_fundamentals_metadata_for_explicit_free():
    with runner.isolated_filesystem():
        result = runner.invoke(
            app,
            [
                "watchlist",
                "--provider",
                "fixture",
                "--fundamentals",
                "free",
                "--limit",
                "1",
                "--save",
                "reports/watchlist.json",
            ],
        )

        payload = json.loads(Path("reports/watchlist.json").read_text())

    assert result.exit_code == 0
    assert payload["metadata"]["fundamentals"] == "off"


def test_watchlist_command_accepts_discovery_filters():
    result = runner.invoke(
        app,
        [
            "watchlist",
            "--country",
            "se,fi",
            "--limit",
            "10",
            "--min-market-cap",
            "250",
            "--max-market-cap",
            "350",
            "--sector",
            "Gaming",
        ],
    )

    assert result.exit_code == 0
    assert "REMEDY" in result.output
    assert "GOFORE" not in result.output


def test_watchlist_command_rejects_blank_country_input():
    result = runner.invoke(app, ["watchlist", "--country", "   "])

    assert result.exit_code != 0
    assert "at least one country code is required" in result.output


def test_deep_dive_command_outputs_report():
    result = runner.invoke(app, ["deep-dive", "FREEM"])

    assert result.exit_code == 0
    assert "Freemelt" in result.output
    assert "Next manual checks" in result.output


def test_deep_dive_command_outputs_json():
    result = runner.invoke(app, ["deep-dive", "FREEM", "--output", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["company"]["ticker"] == "FREEM"
    assert payload["score"]["total"] > 0


def test_sources_test_accepts_fixture_provider_option():
    result = runner.invoke(app, ["sources", "test", "--provider", "fixture"])

    assert result.exit_code == 0
    assert "bundled seed data: ok" in result.output


def test_cli_rejects_invalid_provider_option():
    result = runner.invoke(app, ["watchlist", "--provider", "bad"])

    assert result.exit_code != 0
    assert "provider must be 'fixture' or 'live'" in result.output


def test_watchlist_rejects_invalid_output_before_provider_work(monkeypatch):
    def fail_if_called(name: str):
        raise AssertionError("provider should not be created for invalid output")

    monkeypatch.setattr(cli, "create_provider", fail_if_called)

    result = runner.invoke(app, ["watchlist", "--provider", "live", "--output", "bad"])

    assert result.exit_code != 0
    assert "output must be 'text' or 'json'" in result.output


def test_deep_dive_rejects_invalid_output_before_provider_work(monkeypatch):
    def fail_if_called(name: str):
        raise AssertionError("provider should not be created for invalid output")

    monkeypatch.setattr(cli, "create_provider", fail_if_called)

    result = runner.invoke(app, ["deep-dive", "FREEM", "--provider", "live", "--output", "bad"])

    assert result.exit_code != 0
    assert "output must be 'text' or 'json'" in result.output


def test_watchlist_reports_live_source_errors(monkeypatch):
    class FailingLiveProvider:
        def source_checks(self):
            return [
                SourceCheck(
                    name="nasdaq nordic live data",
                    status="error",
                    detail="network unavailable",
                )
            ]

    monkeypatch.setattr(cli, "create_provider", lambda name: FailingLiveProvider())

    result = runner.invoke(app, ["watchlist", "--provider", "live"])

    assert result.exit_code != 0
    assert "nasdaq nordic live data: error - network unavailable" in result.output


def test_deep_dive_reports_live_source_errors(monkeypatch):
    class FailingLiveProvider:
        def source_checks(self):
            return [
                SourceCheck(
                    name="nasdaq nordic live data",
                    status="error",
                    detail="network unavailable",
                )
            ]

    monkeypatch.setattr(cli, "create_provider", lambda name: FailingLiveProvider())

    result = runner.invoke(app, ["deep-dive", "FREEM", "--provider", "live"])

    assert result.exit_code != 0
    assert "nasdaq nordic live data: error - network unavailable" in result.output


def test_sources_test_command_reports_fixture_status():
    result = runner.invoke(app, ["sources", "test"])

    assert result.exit_code == 0
    assert "bundled seed data: ok" in result.output
