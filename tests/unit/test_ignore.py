from pathlib import Path

import pytest

from obfuscator.errors import ObfuscatorError
from obfuscator.ignore import IgnoreRules
from tests.factories import write_files


def test_root_patterns(tmp_path: Path) -> None:
    write_files(tmp_path, {".obfignore": "*.log\n/root_only.txt\nbuild/\n"})
    rules = IgnoreRules(tmp_path)
    assert rules.is_excluded("a/b.log")
    assert rules.is_excluded("root_only.txt")
    assert not rules.is_excluded("x/root_only.txt")
    assert rules.is_excluded("build/x.py")
    assert rules.is_excluded("deep/build/x.py")
    assert rules.is_excluded("build", is_dir=True)
    assert not rules.is_excluded("src/a.py")


def test_cannot_reinclude_inside_excluded_directory(tmp_path: Path) -> None:
    write_files(tmp_path, {".obfignore": "build/\n!build/keep.py\ndir/*\n!dir/keep.py\n"})
    rules = IgnoreRules(tmp_path)
    assert rules.is_excluded("build/keep.py")
    assert not rules.is_excluded("dir/keep.py")
    assert rules.is_excluded("dir/x.py")


def test_nested_file_overrides_and_is_relative(tmp_path: Path) -> None:
    write_files(tmp_path, {".obfignore": "*.txt\n", "sub/.obfignore": "!keep.txt\n/only_here.md\n"})
    rules = IgnoreRules(tmp_path)
    assert rules.is_excluded("a.txt")
    assert not rules.is_excluded("sub/keep.txt")
    assert rules.is_excluded("sub/other.txt")
    assert rules.is_excluded("sub/only_here.md")
    assert not rules.is_excluded("sub/deeper/only_here.md")
    assert not rules.is_excluded("only_here.md")


def test_no_files_means_nothing_excluded(tmp_path: Path) -> None:
    assert not IgnoreRules(tmp_path).is_excluded("a/b/c.txt")


def test_non_utf8_obfignore_is_e13(tmp_path: Path) -> None:
    write_files(tmp_path, {".obfignore": b"\xff\xfe*.log"})
    with pytest.raises(ObfuscatorError) as info:
        IgnoreRules(tmp_path).is_excluded("a.log")
    assert [f.code for f in info.value.findings] == ["E13"]
