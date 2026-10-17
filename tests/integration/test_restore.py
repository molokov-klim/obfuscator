import os
import shutil
from pathlib import Path

import pytest

from obfuscator.cli import EXIT_OK, EXIT_REFUSED, main
from obfuscator.dictionary import Dictionary, load_dictionary
from obfuscator.errors import ObfuscatorError
from obfuscator.gitio import SubprocessGit
from obfuscator.obfuscate import run_obfuscate
from obfuscator.restore import run_restore
from obfuscator.state import read_state, state_dir_for
from tests.factories import git, make_dictionary, make_project, tree_bytes, write_files

GIT = SubprocessGit()

PROJECT: dict[str, bytes | str] = {
    ".gitignore": "__pycache__/\n*.pyc\n",
    "README.md": "# Pepelac\nAuthor: Ivan Petrov\n",
    "src/pepelac/client.py": "HOST = 'db.pepelac.internal'\r\nclass PepelacClient:\r\n    pass\r\n",
    "src/pepelac/util.py": "def helper():\n    return 'Pepelac'\n",
    "src/old_name.py": "x = 1\n",
    "src/gone.py": "y = 2\n",
    "assets/logo.bin": b"\x00\x01PEPELAC\xff",
}


@pytest.fixture
def dictionary(tmp_path: Path) -> Dictionary:
    return load_dictionary(make_dictionary(tmp_path / "dict.toml"))


def _codes(error: ObfuscatorError) -> set[str]:
    return {f.code for f in error.findings}


def _agent_edits(copy: Path) -> None:
    """Типичная работа агента в копии."""
    client = copy / "src/zqv/client.py"
    client.write_bytes(client.read_bytes().replace(b"    pass\r\n", b"    def ping(self):\r\n        return 'Zqv'\r\n"))
    write_files(copy, {"src/zqv/zqv_tools.py": "from .client import ZqvClient\n"})
    (copy / "src/gone.py").unlink()
    (copy / "src/old_name.py").rename(copy / "src/new_name.py")
    write_files(copy, {"src/zqv/__pycache__/client.cpython-312.pyc": b"\x00junk"})


EXPECTED_AFTER_EDITS = {
    "src/pepelac/client.py": (
        b"HOST = 'db.pepelac.internal'\r\nclass PepelacClient:\r\n    def ping(self):\r\n        return 'Pepelac'\r\n"
    ),
    "src/pepelac/pepelac_tools.py": b"from .client import PepelacClient\n",
    "src/new_name.py": b"x = 1\n",
}


def _expected_tree(project_files: dict[str, bytes]) -> dict[str, bytes]:
    expected = dict(project_files)
    del expected["src/gone.py"]
    del expected["src/old_name.py"]
    expected.update(EXPECTED_AFTER_EDITS)
    return expected


def test_worktree_full_cycle(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    before = tree_bytes(project)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    _agent_edits(copy)

    report = run_restore(copy, "worktree", dictionary, GIT)

    assert tree_bytes(project) == _expected_tree(before)  # SC-003: нетронутое — байт в байт
    assert report.counters == {
        "modified": 1,
        "added": 1,
        "deleted": 1,
        "renamed": 1,
        "not_transferred": 1,
        "restored": 2,
    }
    assert report.files["не перенесены"] == ["src/pepelac/__pycache__/client.cpython-312.pyc"]
    assert sorted(f.code for f in report.warnings) == ["W12", "W13"]


def test_patch_equals_worktree(tmp_path: Path, dictionary: Dictionary) -> None:
    project_a = make_project(tmp_path / "a", PROJECT)
    project_b = make_project(tmp_path / "b", PROJECT)
    for project, copy in ((project_a, tmp_path / "copy-a"), (project_b, tmp_path / "copy-b")):
        run_obfuscate([project], copy, dictionary, GIT)
        _agent_edits(copy)
    run_restore(tmp_path / "copy-a", "worktree", dictionary, GIT)
    patch = tmp_path / "out" / "change.patch"
    report = run_restore(tmp_path / "copy-b", "patch", dictionary, GIT, patch_file=patch)
    assert report.locations["patch"] == str(patch.resolve())
    git(project_b, "apply", str(patch))
    assert tree_bytes(project_b) == tree_bytes(project_a)  # SC-004


def test_patch_applies_outside_git(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "loose", {"notes_pepelac.txt": "Pepelac\r\nline 2\r\n"}, use_git=False)
    copy = tmp_path / "copy"
    run_obfuscate([project / "notes_pepelac.txt"], copy, dictionary, GIT)
    (copy / "notes_zqv.txt").write_bytes(b"Pepelac\r\nline 2 by Zqv\r\n".replace(b"Pepelac", b"Zqv"))
    patch = tmp_path / "p.patch"
    run_restore(copy, "patch", dictionary, GIT, patch_file=patch)
    assert (project / "notes_pepelac.txt").read_bytes() == b"Pepelac\r\nline 2\r\n"
    git(project, "apply", str(patch))
    assert (project / "notes_pepelac.txt").read_bytes() == b"Pepelac\r\nline 2 by Pepelac\r\n"


def test_second_cycle_transfers_only_new_changes(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    (copy / "README.md").write_text("# Zqv\nAuthor: Person One\nv1\n", encoding="utf-8")
    run_restore(copy, "worktree", dictionary, GIT)
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "first")

    (copy / "src/zqv/util.py").write_text("def helper():\n    return 'Zqv!'\n", encoding="utf-8")
    report = run_restore(copy, "worktree", dictionary, GIT)
    assert report.counters["modified"] == 1  # SC-007: README не переносится повторно
    assert (project / "src/pepelac/util.py").read_text(encoding="utf-8") == "def helper():\n    return 'Pepelac!'\n"
    assert (project / "README.md").read_text(encoding="utf-8") == "# Pepelac\nAuthor: Ivan Petrov\nv1\n"


def test_no_changes_is_success_without_writes(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    state_before = (state_dir_for(copy) / "state.json").read_bytes()
    report = run_restore(copy, "worktree", dictionary, GIT)
    assert report.counters["modified"] == 0
    assert (state_dir_for(copy) / "state.json").read_bytes() == state_before
    assert git(project, "status", "--porcelain") == ""


def test_baseline_moves_after_restore(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    _agent_edits(copy)
    run_restore(copy, "worktree", dictionary, GIT)
    state = read_state(state_dir_for(copy))
    paths = {entry.copy_path for entry in state.files}
    assert "src/zqv/zqv_tools.py" in paths
    assert "src/gone.py" not in paths
    assert not any("__pycache__" in path for path in paths)


def test_changed_dictionary_is_e21(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    other = load_dictionary(make_dictionary(tmp_path / "other.toml", '[rules]\n"Pepelac" = "Zqv"\n'))
    with pytest.raises(ObfuscatorError) as info:
        run_restore(copy, "worktree", other, GIT)
    assert _codes(info.value) == {"E21"}


def test_changed_original_is_e22(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    _agent_edits(copy)
    write_files(project, {"README.md": "changed by owner"})
    git(project, "commit", "-q", "-am", "owner")
    with pytest.raises(ObfuscatorError) as info:
        run_restore(copy, "patch", dictionary, GIT, patch_file=tmp_path / "p.patch")
    assert [(f.code, f.path) for f in info.value.findings] == [("E22", "README.md")]  # SC-005
    assert not (tmp_path / "p.patch").exists()


def test_dirty_worktree_is_e23(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    write_files(project, {"scratch.txt": "untracked"})
    with pytest.raises(ObfuscatorError) as info:
        run_restore(copy, "worktree", dictionary, GIT)
    assert _codes(info.value) == {"E23"}


def test_worktree_without_git_is_e24(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "loose", {"a.txt": "Pepelac"}, use_git=False)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    with pytest.raises(ObfuscatorError) as info:
        run_restore(copy, "worktree", dictionary, GIT)
    assert _codes(info.value) == {"E24"}


def test_new_file_over_untracked_original_file_is_e25(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    write_files(project, {"notes.txt": "owner, untracked"})
    write_files(copy, {"notes.txt": "agent"})
    with pytest.raises(ObfuscatorError) as info:
        run_restore(copy, "patch", dictionary, GIT, patch_file=tmp_path / "p.patch")
    assert [(f.code, f.path) for f in info.value.findings] == [("E25", "notes.txt")]
    assert (project / "notes.txt").read_text(encoding="utf-8") == "owner, untracked"


def test_rename_onto_untracked_original_file_is_e25(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    (copy / "src/old_name.py").rename(copy / "src/new.py")
    write_files(project, {"src/new.py": "owner file"})
    with pytest.raises(ObfuscatorError) as info:
        run_restore(copy, "patch", dictionary, GIT, patch_file=tmp_path / "p.patch")
    assert _codes(info.value) == {"E25"}


def test_patch_inside_copy_is_e27(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    with pytest.raises(ObfuscatorError) as info:
        run_restore(copy, "patch", dictionary, GIT, patch_file=copy / "x.patch")
    assert _codes(info.value) == {"E27"}
    existing = tmp_path / "exists.patch"
    existing.write_text("x", encoding="utf-8")
    with pytest.raises(ObfuscatorError) as info:
        run_restore(copy, "patch", dictionary, GIT, patch_file=existing)
    assert _codes(info.value) == {"E27"}


def test_missing_state_is_e20(tmp_path: Path, dictionary: Dictionary) -> None:
    (tmp_path / "copy").mkdir()
    with pytest.raises(ObfuscatorError) as info:
        run_restore(tmp_path / "copy", "worktree", dictionary, GIT)
    assert _codes(info.value) == {"E20"}


def test_warnings_for_agent_text(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    util = copy / "src/zqv/util.py"
    util.write_text(util.read_text(encoding="utf-8") + "# pepelac leaked\n# zQv odd case\n", encoding="utf-8")
    (copy / "assets/logo.bin").write_bytes(b"\x00changed")
    report = run_restore(copy, "worktree", dictionary, GIT)
    found = sorted((f.code, f.path, f.line) for f in report.warnings)
    assert found == [
        ("W10", "src/pepelac/util.py", 3),
        ("W11", "src/pepelac/util.py", 4),
        ("W14", "assets/logo.bin", None),
    ]  # SC-008
    assert (project / "src/pepelac/util.py").read_text(encoding="utf-8").endswith("# zQv odd case\n")


def test_worktree_rolls_back_on_write_error(
    tmp_path: Path, dictionary: Dictionary, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    before = tree_bytes(project)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    _agent_edits(copy)
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("диск переполнен")
        real_replace(src, dst)

    monkeypatch.setattr("obfuscator.restore.os.replace", flaky_replace)
    with pytest.raises(ObfuscatorError) as info:
        run_restore(copy, "worktree", dictionary, GIT)
    assert _codes(info.value) == {"E28"}
    after = {k: v for k, v in tree_bytes(project).items() if ".tmp-" not in k}
    assert after == before  # NFR-011


def test_cli_full_cycle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dictionary = make_dictionary(tmp_path / "dict.toml")
    project = make_project(tmp_path / "proj", PROJECT)
    before = tree_bytes(project)
    copy = tmp_path / "copy"
    assert main(["obfuscate", str(project), "--out", str(copy), "--dict", str(dictionary)]) == EXIT_OK
    _agent_edits(copy)
    assert main(["restore", str(copy), "--worktree", "--dict", str(dictionary)]) == EXIT_OK
    output = capsys.readouterr().out
    assert "obfuscator restore --worktree — OK" in output
    assert "Изменения: изменено 1, добавлено 1, удалено 1, переименовано 1; не перенесено 1" in output
    assert tree_bytes(project) == _expected_tree(before)  # T-45


def test_cli_restore_requires_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["restore", str(tmp_path)]) == 2
    capsys.readouterr()


def test_cli_restore_refusal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dictionary = make_dictionary(tmp_path / "dict.toml")
    (tmp_path / "copy").mkdir()
    code = main(["restore", str(tmp_path / "copy"), "--worktree", "--dict", str(dictionary)])
    assert code == EXIT_REFUSED
    assert "obfuscator restore — ОТКАЗ" in capsys.readouterr().out


def test_copy_can_be_moved_away_and_state_found(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    shutil.rmtree(copy)
    with pytest.raises(ObfuscatorError) as info:
        run_restore(copy, "worktree", dictionary, GIT)
    assert _codes(info.value) == {"E20"}
