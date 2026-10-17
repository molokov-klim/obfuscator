import json
from pathlib import Path

import pytest

from obfuscator.errors import ObfuscatorError
from obfuscator.models import FileEntry
from obfuscator.state import (
    STATE_FILE,
    State,
    from_json,
    now_iso,
    read_state,
    sha256_hex,
    state_dir_for,
    to_json,
    write_state,
)


def _state() -> State:
    return State(
        tool_version="0.2.1",
        created_at="2026-10-15T19:30:00+03:00",
        updated_at="2026-10-15T20:10:00+03:00",
        root="/home/u/Projects/demo",
        inputs=("src", "README.md"),
        git=True,
        dictionary_sha256=sha256_hex(b"dict"),
        files=(
            FileEntry("src/app.py", "src/app.py", "text", sha256_hex(b"o"), sha256_hex(b"c")),
            FileEntry("assets/Кот.png", "assets/Кот.png", "binary", sha256_hex(b"p"), sha256_hex(b"p")),
        ),
    )


def test_roundtrip(tmp_path: Path) -> None:
    write_state(tmp_path / "copy.obfstate", _state())
    assert read_state(tmp_path / "copy.obfstate") == _state()


def test_write_leaves_no_temporary_files(tmp_path: Path) -> None:
    directory = tmp_path / "copy.obfstate"
    write_state(directory, _state())
    write_state(directory, _state())
    assert [p.name for p in directory.iterdir()] == [STATE_FILE]


def test_json_keeps_non_ascii_and_spec_keys() -> None:
    text = to_json(_state())
    assert "Кот.png" in text
    assert list(json.loads(text)) == [
        "format",
        "tool_version",
        "created_at",
        "updated_at",
        "root",
        "inputs",
        "git",
        "dictionary_sha256",
        "files",
    ]


def test_state_dir_is_sibling_of_copy(tmp_path: Path) -> None:
    assert state_dir_for(tmp_path / "demo-x") == tmp_path / "demo-x.obfstate"


def test_missing_state_is_e20(tmp_path: Path) -> None:
    with pytest.raises(ObfuscatorError) as info:
        read_state(tmp_path / "nope.obfstate")
    assert [f.code for f in info.value.findings] == ["E20"]


def _mutated(key: str, value: object) -> str:
    document = json.loads(to_json(_state()))
    document[key] = value
    return json.dumps(document)


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        _mutated("format", 2),
        _mutated("git", "yes"),
        _mutated("inputs", "src"),
        _mutated("root", 1),
        _mutated("files", [{"kind": "text"}]),
        _mutated(
            "files",
            [{"original_path": "a", "copy_path": "a", "kind": "other", "original_sha256": "x", "copy_sha256": "y"}],
        ),
    ],
)
def test_corrupted_state_is_e20(text: str) -> None:
    with pytest.raises(ObfuscatorError) as info:
        from_json(text)
    assert [f.code for f in info.value.findings] == ["E20"]


def test_now_iso_has_timezone() -> None:
    value = now_iso()
    assert value[-6] in "+-"
    assert value[-3] == ":"
