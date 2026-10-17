import re
from pathlib import Path

import pytest

from obfuscator.errors import ERRORS, WARNINGS, ObfuscatorError, finding

SPEC = Path(__file__).resolve().parents[2] / "spec" / "specification.md"


def _spec_codes() -> set[str]:
    text = SPEC.read_text(encoding="utf-8")
    section = text.split("## 7. Ошибки и коды", 1)[1].split("## 8.", 1)[0]
    return set(re.findall(r"^\| ([EW]\d\d) \|", section, flags=re.MULTILINE))


def test_codes_match_specification_section_7() -> None:
    assert set(ERRORS) | set(WARNINGS) == _spec_codes()


def test_finding_message_has_title_and_detail() -> None:
    item = finding("E04", "«AAA»", text="AAA")
    assert item.code == "E04"
    assert item.message == "повтор алиаса: «AAA»"
    assert item.text == "AAA"


def test_unknown_code_is_rejected() -> None:
    with pytest.raises(KeyError):
        finding("E99")


def test_error_requires_findings() -> None:
    with pytest.raises(ValueError, match="хотя бы одну"):
        ObfuscatorError([])


def test_single_error_message() -> None:
    error = ObfuscatorError.single("E02")
    assert [f.code for f in error.findings] == ["E02"]
    assert "E02 словарь пуст" in str(error)
