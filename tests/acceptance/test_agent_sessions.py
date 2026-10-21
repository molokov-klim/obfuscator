"""Синтетическая приёмка полного цикла (замена SC-011 до проверки на реальном проекте).

Модель: случайная сессия агента — набор правок, записанных в пространстве оригинала (с реальными именами). В копию
те же правки попадают через прямую замену, как если бы их сделал агент, видящий только алиасы. После возврата
оригинал обязан совпасть байт в байт с результатом тех же правок, применённых к оригиналу напрямую. Несколько
циклов подряд в одной копии, оба способа возврата, проверка утечек после каждой обфускации.
"""

import random
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from obfuscator.deobfuscate import run_deobfuscate
from obfuscator.dictionary import Dictionary, load_dictionary
from obfuscator.fsio import read_tree
from obfuscator.gitio import SubprocessGit
from obfuscator.inputs import SERVICE_NAMES
from obfuscator.models import Rule
from obfuscator.obfuscate import run_obfuscate
from obfuscator.paths import transform_path
from obfuscator.replacer import Replacer, forward
from obfuscator.restore import run_restore
from obfuscator.scanner import Scanner
from tests.factories import git, make_dictionary, make_project

GIT = SubprocessGit()

DICTIONARY = """[rules]
"Pepelac" = "Zqv"
"pepelac" = "zqv"
"PEPELAC" = "ZQV"
"PepelacBig" = "Wmr"
"db.pepelac.internal" = "host-a7.example"
"Ivan Petrov" = "Person One"
"ivan.petrov@corp.example" = "person.one@mail.example"
"s3cr3t-t0ken-42" = "tok-0001"

[words]
"sim" = "qx"
"Sim" = "Qx"
"SIM" = "QX"
"vi" = "wk"
"""
ORIGINALS = [
    "Pepelac",
    "pepelac",
    "PEPELAC",
    "PepelacBig",
    "db.pepelac.internal",
    "Ivan Petrov",
    "s3cr3t-t0ken-42",
    "sim",
    "Sim",
    "SIM",
    "vi",
    "simClient",
    "sim_x",
    "MySim",
    "SIM-2",
    "vi-ui",
]
WORDS = [
    "def",
    "return",
    "self",
    "value",
    "import",
    "class",
    "x = 1",
    "# note",
    "for i in range(3):",
    "pass",
    "TODO",
    "simple",
    "service",
    "Simulator",
    "SIMPLE",
    "vision",
    "assimilate",
]

Tree = dict[str, bytes]


def _line(rng: random.Random) -> str:
    return " ".join(
        rng.choice(ORIGINALS) if rng.random() < 0.25 else rng.choice(WORDS) for _ in range(rng.randint(1, 6))
    )


def _text_file(rng: random.Random, newline: str) -> bytes:
    return (newline.join(_line(rng) for _ in range(rng.randint(1, 15))) + newline).encode("utf-8")


def _initial_project(rng: random.Random) -> Tree:
    files: Tree = {
        ".gitignore": b"__pycache__/\n*.pyc\n",
        ".obfignore": b"local/\n",
        "README.md": b"# Pepelac\nOwner: Ivan Petrov <ivan.petrov@corp.example>\n",
        "assets/logo.bin": bytes(range(256)),
    }
    for index in range(rng.randint(6, 12)):
        folder = rng.choice(["src/pepelac", "src/pepelac/core", "docs", "config"])
        newline = rng.choice(["\n", "\r\n"])
        files[f"{folder}/file_{index}.txt"] = _text_file(rng, newline)
    return files


def _session(rng: random.Random, tree: Tree, *, counter: list[int]) -> list[Callable[[Tree], None]]:
    """Случайные правки в пространстве оригинала."""
    edits: list[Callable[[Tree], None]] = []
    text_paths = [p for p in sorted(tree) if p.endswith(".txt")]
    for _ in range(rng.randint(1, 6)):
        kind = rng.choice(["edit", "edit", "edit", "add", "delete", "rename"])
        if kind == "edit" and text_paths:
            path = rng.choice(text_paths)
            seed = rng.random()

            def edit(t: Tree, path: str = path, seed: float = seed) -> None:
                if path not in t:
                    return
                local = random.Random(seed)
                data = t[path].decode("utf-8")
                newline = "\r\n" if "\r\n" in data else "\n"
                lines = data.split(newline)[:-1]
                operation = local.choice(["replace", "insert", "delete"])
                index = local.randrange(len(lines) + (1 if operation == "insert" else 0)) if lines else 0
                if operation == "replace" and lines:
                    lines[index] = _line(local)
                elif operation == "delete" and len(lines) > 1:
                    del lines[index]
                else:
                    lines.insert(index, _line(local))
                t[path] = (newline.join(lines) + newline).encode("utf-8")

            edits.append(edit)
        elif kind == "add":
            counter[0] += 1
            name = f"src/pepelac/new_{counter[0]}_{rng.choice(['Pepelac', 'util'])}.txt"
            content = _text_file(rng, "\n")

            def add(t: Tree, name: str = name, content: bytes = content) -> None:
                t[name] = content

            edits.append(add)
        elif kind == "delete" and text_paths:
            path = text_paths.pop(rng.randrange(len(text_paths)))

            def delete(t: Tree, path: str = path) -> None:
                t.pop(path, None)

            edits.append(delete)
        elif kind == "rename" and text_paths:
            path = text_paths.pop(rng.randrange(len(text_paths)))
            counter[0] += 1
            target = f"docs/moved_{counter[0]}_pepelac.txt"

            def rename(t: Tree, path: str = path, target: str = target) -> None:
                if path in t:
                    t[target] = t.pop(path)

            edits.append(rename)
    return edits


def _to_copy(tree: Tree, fwd: Replacer) -> Tree:
    return {
        transform_path(path, fwd): (data if path.endswith(".bin") else fwd.apply(data.decode("utf-8")).encode("utf-8"))
        for path, data in tree.items()
        if path.rsplit("/", 1)[-1] not in SERVICE_NAMES
    }


def _write(root: Path, tree: Tree) -> None:
    for path, data in tree.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _sync_dir(root: Path, tree: Tree) -> None:
    """Приводит каталог копии к дереву: агент правит, добавляет и удаляет файлы."""
    for path in list(read_tree(root)):
        if path not in tree:
            (root / path).unlink()
    _write(root, tree)


def _assert_no_leaks(copy: Path, rules: tuple[Rule, ...]) -> None:
    """Ни одного оригинала: правила подстроки — где угодно, правила по словам — на границе (FR-020, FR-072)."""
    scanner = Scanner.originals(rules)
    for path, data in read_tree(copy).items():
        assert scanner.find(path) == [], path
        assert scanner.find(data.decode("utf-8", errors="replace")) == [], path


@pytest.mark.parametrize("seed", range(12))
def test_random_agent_sessions(tmp_path: Path, seed: int) -> None:
    rng = random.Random(seed)
    dictionary: Dictionary = load_dictionary(make_dictionary(tmp_path / "dict.toml", DICTIONARY))
    fwd = forward(dictionary.rules)
    model = _initial_project(rng)
    project = make_project(tmp_path / "proj", model)
    copy = tmp_path / "copy"
    run_obfuscate([project], copy, dictionary, GIT)
    _assert_no_leaks(copy, dictionary.rules)
    counter = [0]

    for cycle in range(3):
        before_cycle = dict(model)
        for edit in _session(rng, model, counter=counter):
            edit(model)
        # Агент видит только копию: его правки — те же, но в алиасах; плюс мусор, который не переносится.
        copy_tree = _to_copy(model, fwd) | {"src/zqv/__pycache__/mod.cpython-312.pyc": b"\x00junk"}
        _sync_dir(copy, copy_tree)

        if cycle % 2 == 0:
            run_restore(copy, "worktree", dictionary, GIT)
        else:
            patch = tmp_path / f"cycle{cycle}.patch"
            run_restore(copy, "patch", dictionary, GIT, patch_file=patch)
            if patch.exists():
                git(project, "apply", str(patch))
        actual = {path: data for path, data in read_tree(project).items()}
        assert actual == model, f"seed={seed} cycle={cycle}"
        git(project, "add", "-A")
        if model != before_cycle:
            git(project, "commit", "-q", "-m", f"cycle {cycle}")

    # После всех циклов повторная обфускация в новую копию снова без утечек и совпадает с моделью.
    shutil.rmtree(copy)
    shutil.rmtree(tmp_path / "copy.obfstate")
    run_obfuscate([project], copy, dictionary, GIT)
    _assert_no_leaks(copy, dictionary.rules)
    assert read_tree(copy) == _to_copy(model, fwd)


@pytest.mark.parametrize("seed", range(12))
def test_random_external_files_deobfuscate(tmp_path: Path, seed: int) -> None:
    """T-83: внешняя сторона присылает новые файлы на основе копии; деобфускация возвращает оригиналы (SC-017)."""
    rng = random.Random(1000 + seed)
    dictionary: Dictionary = load_dictionary(make_dictionary(tmp_path / "dict.toml", DICTIONARY))
    fwd = forward(dictionary.rules)
    # Модель ответа в пространстве оригинала: новые файлы, каталоги с оригиналами в именах, CRLF и LF.
    expected: Tree = {}
    for index in range(rng.randint(3, 10)):
        folder = rng.choice(["answer", "answer/pepelac", "answer/Pepelac_sim", "answer/notes-vi"])
        newline = rng.choice(["\n", "\r\n"])
        expected[f"{folder}/reply_{index}_{rng.choice(['Pepelac', 'simClient', 'plain'])}.md"] = _text_file(
            rng, newline
        )
    expected["answer/blob.bin"] = bytes(range(256))
    # Внешняя сторона видела только алиасы.
    inbox = tmp_path / "inbox"
    _write(inbox, _to_copy(expected, fwd))
    before = read_tree(inbox)

    out = tmp_path / "restored"
    report = run_deobfuscate([inbox], out, dictionary)

    assert read_tree(out) == expected
    assert read_tree(inbox) == before
    assert not [w for w in report.warnings if w.code in {"W10", "W11"}], report.warnings
