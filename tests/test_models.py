from openclaw import __version__
from openclaw.cli import app


def test_package_exposes_version():
    assert __version__ == "0.1.0"


def test_console_script_target_exposes_app():
    assert app is not None
