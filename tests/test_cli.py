from openclaw.cli import app


def test_console_script_target_exposes_app():
    assert app is not None
