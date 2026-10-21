import os
from pathlib import Path

import pytest

from obfuscator.cli import EXIT_OK, EXIT_REFUSED, main
from obfuscator.deobfuscate import run_deobfuscate
from obfuscator.dictionary import Dictionary, load_dictionary
from obfuscator.errors import ObfuscatorError
from obfuscator.gitio import SubprocessGit
from obfuscator.obfuscate import run_obfuscate
from obfuscator.restore import run_restore
from obfuscator.state import state_dir_for
from tests.factories import DICTIONARY, make_dictionary, make_project, tree_bytes, write_files

GIT = SubprocessGit()

WORDS_DICTIONARY = (
    DICTIONARY
    + """
[words]
"sim" = "qx"
"Sim" = "Qx"
"SIM" = "QX"
"""
)

PROJECT: dict[str, bytes | str] = {
    "README.md": "# Pepelac\nService for Ivan Petrov.\n",
    "src/pepelac/client.py": "HOST = 'db.pepelac.internal'\r\nclass PepelacClient:\r\n    sim_mode = 'simple'\r\n",
    "src/bom.txt": "\ufeffPEPELAC with BOM\n".encode(),
    "src/empty.txt": b"",
    "assets/logo.bin": b"\x00\x01\x02\xff",
}


@pytest.fixture
def dictionary(tmp_path: Path) -> Dictionary:
    return load_dictionary(make_dictionary(tmp_path / "dict.toml", WORDS_DICTIONARY))


def _codes(error: ObfuscatorError) -> set[str]:
    return {f.code for f in error.findings}


def test_external_files_are_restored_and_input_untouched(tmp_path: Path, dictionary: Dictionary) -> None:
    inbox = tmp_path / "inbox"
    write_files(
        inbox,
        {
            "zqv_notes.md": "Zqv talks to host-a7.example\r\nqx-x, qxClient, MyQx, QX_X; qxample stays\r\n",
            "Wmr/Person One.txt": "\ufeffPerson One owns ZQV\n",
            "plain.txt": "nothing here",
            "blob.bin": b"\x00\xff",
        },
    )
    before = tree_bytes(inbox)
    out = tmp_path / "restored"

    report = run_deobfuscate([inbox], out, dictionary)

    assert tree_bytes(out) == {
        "pepelac_notes.md": (
            b"Pepelac talks to db.pepelac.internal\r\nsim-x, simClient, MySim, SIM_X; qxample stays\r\n"
        ),
        "PepelacBig/Ivan Petrov.txt": "\ufeffIvan Petrov owns PEPELAC\n".encode(),
        "plain.txt": b"nothing here",
        "blob.bin": b"\x00\xff",
    }
    assert tree_bytes(inbox) == before
    assert report.warnings == []
    assert report.per_rule["Zqv"] == 1
    assert report.per_rule["qx"] == 2
    assert report.counters["paths_changed"] == 2
    assert report.counters["processed"] == 4
    assert report.counters["binary"] == 1


def test_deobfuscate_of_unchanged_copy_gives_input_byte_for_byte(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    out = tmp_path / "restored"
    run_deobfuscate([copy], out, dictionary)
    assert tree_bytes(out) == tree_bytes(project)


def test_single_file_and_several_paths(tmp_path: Path, dictionary: Dictionary) -> None:
    inbox = tmp_path / "inbox"
    write_files(inbox, {"a/zqv.txt": "Zqv", "b/c.txt": "qx", "d.txt": "untouched"})
    run_deobfuscate([inbox / "a" / "zqv.txt"], tmp_path / "one", dictionary)
    assert tree_bytes(tmp_path / "one") == {"pepelac.txt": b"Pepelac"}
    run_deobfuscate([inbox / "a", inbox / "b" / "c.txt"], tmp_path / "two", dictionary)
    assert tree_bytes(tmp_path / "two") == {"a/pepelac.txt": b"Pepelac", "b/c.txt": b"sim"}


def test_git_dir_and_dictionary_are_skipped_untracked_files_included(tmp_path: Path) -> None:
    inbox = make_project(tmp_path / "inbox", {"tracked.txt": "Zqv"})
    write_files(inbox, {"untracked.txt": "zqv"})
    dictionary = load_dictionary(make_dictionary(inbox / "dict.toml", WORDS_DICTIONARY))
    out = tmp_path / "restored"
    report = run_deobfuscate([inbox], out, dictionary)
    assert tree_bytes(out) == {"tracked.txt": b"Pepelac", "untracked.txt": b"pepelac"}
    assert report.files["пропущены"] == ["dict.toml"]


def test_other_case_alias_is_w11_and_not_restored(tmp_path: Path, dictionary: Dictionary) -> None:
    inbox = tmp_path / "inbox"
    write_files(inbox, {"a.txt": "ok Zqv\nbad ZQv here\n", "zQV.txt": "x"})
    report = run_deobfuscate([inbox], tmp_path / "out", dictionary)
    assert tree_bytes(tmp_path / "out") == {"a.txt": b"ok Pepelac\nbad ZQv here\n", "zQV.txt": b"x"}
    w11 = [(f.path, f.line, f.text) for f in report.warnings if f.code == "W11"]
    assert ("a.txt", 2, "ZQv") in w11
    assert ("zQV.txt", None, "zQV") in w11


def test_original_already_in_input_is_w10(tmp_path: Path, dictionary: Dictionary) -> None:
    inbox = tmp_path / "inbox"
    write_files(inbox, {"a.txt": "line\nPepelac already\nsimple is fine\n"})
    report = run_deobfuscate([inbox], tmp_path / "out", dictionary)
    assert [(f.code, f.path, f.line, f.text) for f in report.warnings] == [("W10", "a.txt", 2, "Pepelac")]


def test_alias_in_binary_is_w15(tmp_path: Path, dictionary: Dictionary) -> None:
    inbox = tmp_path / "inbox"
    write_files(inbox, {"img.bin": b"\xff\x00Zqv\x00"})
    report = run_deobfuscate([inbox], tmp_path / "out", dictionary)
    assert [f.code for f in report.warnings] == ["W15"]
    assert tree_bytes(tmp_path / "out") == {"img.bin": b"\xff\x00Zqv\x00"}


def test_symlink_is_skipped_with_w03(tmp_path: Path, dictionary: Dictionary) -> None:
    inbox = tmp_path / "inbox"
    write_files(inbox, {"a.txt": "Zqv"})
    try:
        os.symlink(inbox / "a.txt", inbox / "link.txt")
    except OSError:
        pytest.skip("символические ссылки недоступны")
    report = run_deobfuscate([inbox], tmp_path / "out", dictionary)
    assert [f.code for f in report.warnings] == ["W03"]
    assert set(tree_bytes(tmp_path / "out")) == {"a.txt"}


def test_non_empty_out_is_e08_and_nothing_written(tmp_path: Path, dictionary: Dictionary) -> None:
    inbox = tmp_path / "inbox"
    write_files(inbox, {"a.txt": "Zqv"})
    out = tmp_path / "out"
    write_files(out, {"keep.txt": "mine"})
    with pytest.raises(ObfuscatorError) as error:
        run_deobfuscate([inbox], out, dictionary)
    assert _codes(error.value) == {"E08"}
    assert tree_bytes(out) == {"keep.txt": b"mine"}


def test_empty_out_is_accepted(tmp_path: Path, dictionary: Dictionary) -> None:
    inbox = tmp_path / "inbox"
    write_files(inbox, {"a.txt": "Zqv"})
    out = tmp_path / "out"
    out.mkdir()
    run_deobfuscate([inbox], out, dictionary)
    assert tree_bytes(out) == {"a.txt": b"Pepelac"}


@pytest.mark.parametrize("where", ["inside", "around"])
def test_out_overlapping_input_is_e08(tmp_path: Path, dictionary: Dictionary, where: str) -> None:
    inbox = tmp_path / "inbox"
    write_files(inbox, {"a.txt": "Zqv"})
    if where == "inside":
        paths, out = [inbox], inbox / "out"
    else:
        paths, out = [inbox], tmp_path
    with pytest.raises(ObfuscatorError) as error:
        run_deobfuscate(paths, out, dictionary)
    assert _codes(error.value) == {"E08"}
    assert not (inbox / "out").exists()


def test_missing_path_is_e07(tmp_path: Path, dictionary: Dictionary) -> None:
    with pytest.raises(ObfuscatorError) as error:
        run_deobfuscate([tmp_path / "nope"], tmp_path / "out", dictionary)
    assert _codes(error.value) == {"E07"}


def test_invalid_restored_path_is_e10(tmp_path: Path) -> None:
    dictionary = load_dictionary(make_dictionary(tmp_path / "dict.toml", '[rules]\n"a:b" = "ab0"\n'))
    inbox = tmp_path / "inbox"
    write_files(inbox, {"ab0.txt": "x"})
    out = tmp_path / "out"
    with pytest.raises(ObfuscatorError) as error:
        run_deobfuscate([inbox], out, dictionary)
    assert _codes(error.value) == {"E10"}
    assert not out.exists()


def test_cli_deobfuscate_does_not_use_git(
    tmp_path: Path, dictionary: Dictionary, capsys: pytest.CaptureFixture[str]
) -> None:
    class NoGit:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"git не должен вызываться: {name}")

    inbox = tmp_path / "inbox"
    write_files(inbox, {"a.txt": "Zqv and ZQv\n"})
    code = main(
        ["deobfuscate", str(inbox), "--out", str(tmp_path / "out"), "--dict", str(dictionary.path)],
        git=NoGit(),  # type: ignore[arg-type]
    )
    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert "obfuscator deobfuscate — OK" in captured.out
    assert "Zqv → Pepelac" in captured.out
    assert f"Результат: {(tmp_path / 'out').resolve()}" in captured.out
    assert "W11 a.txt:1" in captured.err


def test_cli_deobfuscate_refusal(tmp_path: Path, dictionary: Dictionary, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["deobfuscate", str(tmp_path / "nope"), "--out", str(tmp_path / "o"), "--dict", str(dictionary.path)])
    captured = capsys.readouterr()
    assert code == EXIT_REFUSED
    assert "obfuscator deobfuscate — ОТКАЗ" in captured.out
    assert "E07" in captured.err


# --- obfuscate --no-state (FR-088, SC-018) ---


def test_no_state_gives_same_copy_without_state(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    run_obfuscate([project], tmp_path / "with", dictionary, GIT)
    report = run_obfuscate([project], tmp_path / "without", dictionary, GIT, no_state=True)
    assert tree_bytes(tmp_path / "without") == tree_bytes(tmp_path / "with")
    assert not state_dir_for(tmp_path / "without").exists()
    assert "state" not in report.locations
    with pytest.raises(ObfuscatorError) as error:
        run_restore(tmp_path / "without", "patch", dictionary, GIT, patch_file=tmp_path / "p.patch")
    assert _codes(error.value) == {"E20"}


def test_no_state_keeps_leak_check(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", {"a.txt": "PePeLaC"})
    with pytest.raises(ObfuscatorError) as error:
        run_obfuscate([project], tmp_path / "copy", dictionary, GIT, no_state=True)
    assert _codes(error.value) == {"E12"}
    assert not (tmp_path / "copy").exists()


def test_no_state_into_own_copy_is_e08(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    with pytest.raises(ObfuscatorError) as error:
        run_obfuscate([project], copy, dictionary, GIT, no_state=True)
    assert _codes(error.value) == {"E08"}
    assert state_dir_for(copy).exists()


def test_no_state_into_non_empty_dir_is_e08(tmp_path: Path, dictionary: Dictionary) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    out = tmp_path / "out"
    write_files(out, {"x.txt": "x"})
    with pytest.raises(ObfuscatorError) as error:
        run_obfuscate([project], out, dictionary, GIT, no_state=True)
    assert _codes(error.value) == {"E08"}


def test_cli_no_state_report(tmp_path: Path, dictionary: Dictionary, capsys: pytest.CaptureFixture[str]) -> None:
    project = make_project(tmp_path / "proj", PROJECT)
    out = tmp_path / "copy"
    code = main(["obfuscate", str(project), "--out", str(out), "--no-state", "--dict", str(dictionary.path)])
    output = capsys.readouterr().out
    assert code == EXIT_OK
    assert "Состояние: не создано (--no-state); ответ возвращается командой deobfuscate" in output
    assert not state_dir_for(out).exists()
