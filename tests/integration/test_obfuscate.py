import os
from pathlib import Path

import pytest

from obfuscator.cli import EXIT_OK, EXIT_REFUSED, main
from obfuscator.dictionary import load_dictionary
from obfuscator.errors import ObfuscatorError
from obfuscator.fsio import hash_tree
from obfuscator.gitio import SubprocessGit
from obfuscator.obfuscate import run_obfuscate
from obfuscator.replacer import backward
from obfuscator.state import read_state, state_dir_for
from tests.factories import git, make_dictionary, make_project, tree_bytes, write_files

GIT = SubprocessGit()

PROJECT: dict[str, bytes | str] = {
    "README.md": "# Pepelac\nService for Ivan Petrov.\n",
    "src/pepelac/__init__.py": "from .client import PepelacClient\n",
    "src/pepelac/client.py": "HOST = 'db.pepelac.internal'\r\nclass PepelacClient:\r\n    big = 'PepelacBig'\r\n",
    "src/bom.txt": "﻿PEPELAC with BOM\n".encode(),
    "src/empty.txt": b"",
    "assets/logo.bin": b"\x00\x01\x02\xff",
    "config/no-newline.cfg": "name=Pepelac",
}


def _codes(error: ObfuscatorError) -> set[str]:
    return {f.code for f in error.findings}


@pytest.fixture
def dictionary(tmp_path: Path) -> Path:
    return make_dictionary(tmp_path / "dict.toml")


def _obfuscate(paths: list[Path], out: Path, dictionary: Path) -> None:
    run_obfuscate(paths, out, load_dictionary(dictionary), GIT)


def test_copy_has_no_originals_and_restores_byte_for_byte(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    out = tmp_path / "copy"
    _obfuscate([project], out, dictionary)

    copy = tree_bytes(out)
    rules = load_dictionary(dictionary).rules
    for path, data in copy.items():
        lowered = (path + "\n" + data.decode("utf-8", errors="replace")).casefold()
        assert "pepelac" not in lowered, path  # SC-001
        assert "ivan petrov" not in lowered, path
    assert "src/zqv/client.py" in copy
    bwd = backward(rules)
    restored = {
        "/".join(bwd.apply(part) for part in path.split("/")): (
            bwd.apply(data.decode("utf-8")).encode("utf-8") if path != "assets/logo.bin" else data
        )
        for path, data in copy.items()
    }
    original = tree_bytes(project)
    assert restored == original  # SC-002: CRLF, BOM, пустой, без перевода строки, бинарный


def test_state_written_next_to_copy(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    out = tmp_path / "copy"
    _obfuscate([project], out, dictionary)
    state = read_state(state_dir_for(out))
    assert state.git is True
    assert state.inputs == (".",)
    assert Path(state.root) == project.resolve()
    assert {f.copy_path: f.copy_sha256 for f in state.files} == hash_tree(out)
    assert hash_tree(state_dir_for(out) / "baseline") == hash_tree(out)


def test_untracked_and_gitignored_files_are_not_copied(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", {**PROJECT, ".gitignore": "secret.env\n"})
    write_files(project, {"secret.env": "TOKEN=1", "untracked.txt": "x"})
    out = tmp_path / "copy"
    _obfuscate([project], out, dictionary)
    copy = tree_bytes(out)
    assert "secret.env" not in copy
    assert "untracked.txt" not in copy
    assert ".gitignore" in copy


def test_obfignore_and_allow_files_never_copied(tmp_path: Path, dictionary: Path) -> None:
    files = {
        **PROJECT,
        ".obfignore": "*.log\nbuild/\n!build/keep.txt\n",
        "sub/.obfignore": "local.txt\n",
        ".obfallow.toml": '[[allow]]\ntext = "x"\n',
        "a.log": "log",
        "build/keep.txt": "kept?",
        "sub/local.txt": "x",
        "sub/other.txt": "y",
        "local.txt": "root local is not excluded",
    }
    project = make_project(tmp_path / "proj", files)
    out = tmp_path / "copy"
    _obfuscate([project], out, dictionary)
    copy = tree_bytes(out)
    assert ".obfignore" not in copy  # SC-014
    assert "sub/.obfignore" not in copy
    assert ".obfallow.toml" not in copy
    assert "a.log" not in copy
    assert "build/keep.txt" not in copy  # каталог исключён — вернуть файл нельзя (как в git)
    assert "sub/local.txt" not in copy
    assert "sub/other.txt" in copy
    assert "local.txt" in copy  # SC-013


def test_obfignore_without_git(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", {"a.txt": "a", "skip/b.txt": "b", ".obfignore": "skip/\n"}, use_git=False)
    out = tmp_path / "copy"
    _obfuscate([project], out, dictionary)
    assert set(tree_bytes(out)) == {"a.txt"}


def test_several_paths_inside_git_keep_relative_paths(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    out = tmp_path / "copy"
    _obfuscate([project / "src" / "pepelac", project / "README.md"], out, dictionary)
    assert set(tree_bytes(out)) == {"README.md", "src/zqv/__init__.py", "src/zqv/client.py"}  # SC-012
    state = read_state(state_dir_for(out))
    assert state.inputs == ("README.md", "src/pepelac")


def test_single_file_without_git(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "loose", {"pepelac_notes.txt": "Pepelac"}, use_git=False)
    out = tmp_path / "copy"
    _obfuscate([project / "pepelac_notes.txt"], out, dictionary)
    assert tree_bytes(out) == {"zqv_notes.txt": b"Zqv"}
    assert read_state(state_dir_for(out)).git is False


def test_dictionary_inside_input_is_never_copied(tmp_path: Path) -> None:
    project = make_project(tmp_path / "loose", {"a.txt": "Pepelac"}, use_git=False)
    dictionary = make_dictionary(project / "dictionary.toml")
    out = tmp_path / "copy"
    _obfuscate([project], out, dictionary)
    assert set(tree_bytes(out)) == {"a.txt"}


def test_mixed_git_and_plain_paths_is_e07(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    plain = make_project(tmp_path / "plain", {"x.txt": "x"}, use_git=False)
    with pytest.raises(ObfuscatorError) as info:
        _obfuscate([project, plain], tmp_path / "copy", dictionary)
    assert _codes(info.value) == {"E07"}


def test_missing_path_is_e07(tmp_path: Path, dictionary: Path) -> None:
    with pytest.raises(ObfuscatorError) as info:
        _obfuscate([tmp_path / "nope"], tmp_path / "copy", dictionary)
    assert _codes(info.value) == {"E07"}


def test_non_empty_foreign_out_is_e08(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    out = tmp_path / "copy"
    write_files(out, {"foreign.txt": "x"})
    with pytest.raises(ObfuscatorError) as info:
        _obfuscate([project], out, dictionary)
    assert _codes(info.value) == {"E08"}
    assert tree_bytes(out) == {"foreign.txt": b"x"}


def test_out_inside_input_is_e08(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", PROJECT, use_git=False)
    with pytest.raises(ObfuscatorError) as info:
        _obfuscate([project], project / "copy", dictionary)
    assert _codes(info.value) == {"E08"}


def test_reobfuscate_own_unchanged_copy(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    out = tmp_path / "copy"
    _obfuscate([project], out, dictionary)
    _obfuscate([project], out, dictionary)
    assert "README.md" in tree_bytes(out)
    assert not [p for p in tmp_path.iterdir() if ".tmp-" in p.name or ".old-" in p.name]


def test_reobfuscate_changed_copy_is_e08(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    out = tmp_path / "copy"
    _obfuscate([project], out, dictionary)
    (out / "README.md").write_text("agent edit", encoding="utf-8")
    with pytest.raises(ObfuscatorError) as info:
        _obfuscate([project], out, dictionary)
    assert _codes(info.value) == {"E08"}
    assert (out / "README.md").read_text(encoding="utf-8") == "agent edit"


def test_alias_in_project_is_e09(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", {"a.txt": "line\nalready Zqv here\n"})
    with pytest.raises(ObfuscatorError) as info:
        _obfuscate([project], tmp_path / "copy", dictionary)
    assert [(f.code, f.path, f.line) for f in info.value.findings] == [("E09", "a.txt", 2)]
    assert not (tmp_path / "copy").exists()


def test_invalid_path_after_replacement_is_e10(tmp_path: Path) -> None:
    dictionary = make_dictionary(tmp_path / "d.toml", '[rules]\n"printer" = "CON"\n')
    project = make_project(tmp_path / "proj", {"printer.txt": "x"}, use_git=False)
    with pytest.raises(ObfuscatorError) as info:
        _obfuscate([project], tmp_path / "copy", dictionary)
    assert _codes(info.value) == {"E10"}


def test_ambiguous_reverse_is_e11(tmp_path: Path) -> None:
    dictionary = make_dictionary(tmp_path / "d.toml", '[rules]\n"q" = "bz"\n"w" = "ab"\n')
    project = make_project(tmp_path / "proj", {"f.txt": "aq\n"}, use_git=False)
    with pytest.raises(ObfuscatorError) as info:
        _obfuscate([project], tmp_path / "copy", dictionary)
    assert _codes(info.value) == {"E11"}


def test_other_case_spelling_is_e12_until_allowed(tmp_path: Path) -> None:
    dictionary = make_dictionary(tmp_path / "d.toml", '[rules]\n"Pepelac" = "Zqv"\n')
    project = make_project(tmp_path / "proj", {"src/app.py": "import x\nuse pepelac\n"}, use_git=False)
    with pytest.raises(ObfuscatorError) as info:
        _obfuscate([project], tmp_path / "copy", dictionary)
    assert [(f.code, f.path, f.line, f.text) for f in info.value.findings] == [("E12", "src/app.py", 2, "pepelac")]
    write_files(project, {".obfallow.toml": '[[allow]]\ntext = "pepelac"\nfiles = ["src/**"]\n'})
    _obfuscate([project], tmp_path / "copy", dictionary)  # SC-006
    assert tree_bytes(tmp_path / "copy") == {"src/app.py": b"import x\nuse pepelac\n"}


def test_original_in_binary_is_w01(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", {"a.bin": b"\xff\xfePEPELAC\x00"}, use_git=False)
    report = run_obfuscate([project], tmp_path / "copy", load_dictionary(dictionary), GIT)
    assert [f.code for f in report.warnings] == ["W01"]


def test_symlink_is_skipped_with_w03(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", {"a.txt": "a"}, use_git=False)
    try:
        os.symlink(project / "a.txt", project / "link.txt")
    except OSError:
        pytest.skip("символические ссылки недоступны")
    report = run_obfuscate([project], tmp_path / "copy", load_dictionary(dictionary), GIT)
    assert [f.code for f in report.warnings] == ["W03"]
    assert set(tree_bytes(tmp_path / "copy")) == {"a.txt"}


def test_report_counts(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", {"a.txt": "Pepelac pepelac Pepelac", "pepelac.md": "x"})
    report = run_obfuscate([project], tmp_path / "copy", load_dictionary(dictionary), GIT)
    assert report.per_rule == {"Pepelac": 2, "pepelac": 1}
    assert report.counters["paths_changed"] == 1
    assert report.counters["copied"] == 2


def test_deleted_tracked_file_is_ignored(tmp_path: Path, dictionary: Path) -> None:
    project = make_project(tmp_path / "proj", {"a.txt": "a", "b.txt": "b"})
    (project / "b.txt").unlink()
    _obfuscate([project], tmp_path / "copy", dictionary)
    assert set(tree_bytes(tmp_path / "copy")) == {"a.txt"}
    assert git(project, "status", "--short").strip() == "D b.txt"


def test_cli_obfuscate_ok(tmp_path: Path, dictionary: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    code = main(["obfuscate", str(project), "--out", str(tmp_path / "copy"), "--dict", str(dictionary)])
    output = capsys.readouterr().out
    assert code == EXIT_OK
    assert "obfuscator obfuscate — OK" in output
    assert "Pepelac → Zqv" in output
    assert f"Копия: {(tmp_path / 'copy').resolve()}" in output


def test_cli_dictionary_from_environment(
    tmp_path: Path, dictionary: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    monkeypatch.setenv("OBFUSCATOR_DICT", str(dictionary))
    assert main(["obfuscate", str(project), "--out", str(tmp_path / "copy")]) == EXIT_OK
    capsys.readouterr()


def test_cli_refusal_exit_code_and_stderr(tmp_path: Path, dictionary: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["obfuscate", str(tmp_path / "nope"), "--out", str(tmp_path / "copy"), "--dict", str(dictionary)])
    captured = capsys.readouterr()
    assert code == EXIT_REFUSED
    assert "— ОТКАЗ" in captured.out
    assert captured.err.startswith("E07 ")
