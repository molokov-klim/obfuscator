from pathlib import Path

import pytest

from obfuscator.allow import ALLOW_FILE, AllowEntry, load_allow, parse_allow
from obfuscator.errors import ObfuscatorError

VALID = b"""
[[allow]]
text = "max"
files = ["src/**/*.py"]

[[allow]]
text = "PEPELAC_ENV"
"""


def test_parse_entries_in_order() -> None:
    allow = parse_allow(VALID, "t")
    assert allow.entries == (
        AllowEntry(text="max", files=("src/**/*.py",)),
        AllowEntry(text="PEPELAC_ENV", files=None),
    )


def test_text_must_match_exactly() -> None:
    allow = parse_allow(VALID, "t")
    assert allow.allows("PEPELAC_ENV", "any/file.txt")
    assert not allow.allows("pepelac_env", "any/file.txt")


def test_files_patterns_limit_paths() -> None:
    allow = parse_allow(VALID, "t")
    assert allow.allows("max", "src/a/b.py")
    assert not allow.allows("max", "docs/readme.md")


def test_missing_file_gives_empty_list(tmp_path: Path) -> None:
    assert load_allow(tmp_path).entries == ()


def test_load_from_root(tmp_path: Path) -> None:
    (tmp_path / ALLOW_FILE).write_bytes(VALID)
    assert len(load_allow(tmp_path).entries) == 2


def test_empty_document_is_allowed() -> None:
    assert parse_allow(b"", "t").entries == ()


@pytest.mark.parametrize(
    "content",
    [
        b"bad = [",
        b"other = 1\n",
        b'allow = "x"\n',
        b"[[allow]]\nfiles = ['a']\n",
        b'[[allow]]\ntext = ""\n',
        b'[[allow]]\ntext = "a\\nb"\n',
        b'[[allow]]\ntext = "a"\nfiles = []\n',
        b'[[allow]]\ntext = "a"\nfiles = [""]\n',
        b'[[allow]]\ntext = "a"\nfiles = "src"\n',
        b'[[allow]]\ntext = "a"\nextra = 1\n',
    ],
)
def test_bad_format_is_e13(content: bytes) -> None:
    with pytest.raises(ObfuscatorError) as info:
        parse_allow(content, "t")
    assert [f.code for f in info.value.findings] == ["E13"]
