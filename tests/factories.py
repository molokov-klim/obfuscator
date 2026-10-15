"""Синтетические проекты для тестов: строятся кодом, чтобы байты не искажались git на Windows."""

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
}

DICTIONARY = """[rules]
"Pepelac" = "Zqv"
"pepelac" = "zqv"
"PEPELAC" = "ZQV"
"PepelacBig" = "Wmr"
"db.pepelac.internal" = "host-a7.example"
"Ivan Petrov" = "Person One"
"""


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.autocrlf=false", *args],
        cwd=cwd,
        env=GIT_ENV,
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def write_files(root: Path, files: Mapping[str, bytes | str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)


def make_project(root: Path, files: Mapping[str, bytes | str], *, use_git: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    write_files(root, files)
    if use_git:
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "core.autocrlf", "false")
        git(root, "config", "commit.gpgsign", "false")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "init")
    return root


def make_dictionary(path: Path, content: str = DICTIONARY) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def tree_bytes(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            path = Path(current) / name
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files
