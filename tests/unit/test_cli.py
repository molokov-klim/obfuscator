import pytest

from obfuscator import __version__
from obfuscator.cli import EXIT_OK, EXIT_USAGE, main


def test_version_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == EXIT_OK
    assert capsys.readouterr().out.strip() == f"obfuscator {__version__}"


def test_no_arguments_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_USAGE
    assert "usage: obfuscator" in capsys.readouterr().err


def test_unknown_argument_is_usage_error() -> None:
    assert main(["--no-such-option"]) == EXIT_USAGE
