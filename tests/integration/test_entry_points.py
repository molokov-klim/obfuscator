import subprocess
import sys

from obfuscator import __version__


def test_python_m_obfuscator_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "obfuscator", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"obfuscator {__version__}"
