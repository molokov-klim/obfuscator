from pathlib import Path

import pytest

from obfuscator.errors import ObfuscatorError
from obfuscator.gitio import SubprocessGit
from tests.factories import make_project, write_files

GIT = SubprocessGit()


def test_toplevel_inside_and_outside(tmp_path: Path) -> None:
    project = make_project(tmp_path / "proj", {"src/a.txt": "a"})
    assert GIT.toplevel(project / "src") == project.resolve()
    plain = make_project(tmp_path / "plain", {"a.txt": "a"}, use_git=False)
    assert GIT.toplevel(plain) is None


def test_tracked_files_are_literal(tmp_path: Path) -> None:
    try:
        project = make_project(tmp_path / "proj", {"x/a*b.txt": "1", "x/aZb.txt": "2", "y.txt": "3"})
    except OSError:
        pytest.skip("имя с * недопустимо в этой файловой системе")
    assert GIT.tracked_files(project, ["x/a*b.txt"]) == ["x/a*b.txt"]
    assert GIT.tracked_files(project, ["x"]) == ["x/a*b.txt", "x/aZb.txt"]


def test_status_limited_to_paths(tmp_path: Path) -> None:
    project = make_project(tmp_path / "proj", {"src/a.txt": "a", "docs/d.md": "d"})
    write_files(project, {"docs/d.md": "changed", "src/new.txt": "n"})
    assert GIT.status(project, ["src"]) == ["?? src/new.txt"]
    assert GIT.status(project, ["docs"]) == [" M docs/d.md"]


def test_is_ignored_for_missing_paths(tmp_path: Path) -> None:
    project = make_project(tmp_path / "proj", {".gitignore": "*.log\nbuild/\n", "a.txt": "a"})
    assert GIT.is_ignored(project, "x/y.log")
    assert GIT.is_ignored(project, "build/out.bin")
    assert not GIT.is_ignored(project, "x/y.txt")


def test_missing_git_is_e26(tmp_path: Path) -> None:
    with pytest.raises(ObfuscatorError) as info:
        SubprocessGit("git-does-not-exist").toplevel(tmp_path)
    assert [f.code for f in info.value.findings] == ["E26"]
