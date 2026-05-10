import json
import subprocess
import sys

from typer.testing import CliRunner

from investmentagent.cli import app


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


def test_sources_test_command_reports_fixture_status():
    result = runner.invoke(app, ["sources", "test"])

    assert result.exit_code == 0
    assert "bundled seed data: ok" in result.output
