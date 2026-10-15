"""Производительность (SC-010, NFR-021): запуск — ``uv run pytest -m slow -s``."""

import random
import string
import time
from pathlib import Path

import pytest

from obfuscator.dictionary import load_dictionary
from obfuscator.gitio import SubprocessGit
from obfuscator.obfuscate import run_obfuscate
from obfuscator.restore import run_restore
from tests.factories import make_dictionary, make_project

FILES = 1000
TOTAL_BYTES = 20_000_000
RULES = 500
LIMIT_SECONDS = 10.0


def _project(tmp_path: Path) -> tuple[Path, Path]:
    rng = random.Random(42)
    originals = sorted(
        {"".join(rng.choice(string.ascii_letters) for _ in range(rng.randint(6, 16))) for _ in range(RULES)}
    )
    lines = ["[rules]"] + [f'"{original}" = "zz{index:04d}q"' for index, original in enumerate(originals)]
    dictionary = make_dictionary(tmp_path / "dict.toml", "\n".join(lines) + "\n")
    words = ["return", "self", "value", "import", "class", "def", "x = 1", "(", ")", "for", "in"]
    per_file = TOTAL_BYTES // FILES
    files: dict[str, bytes | str] = {}
    for index in range(FILES):
        parts: list[str] = []
        size = 0
        while size < per_file:
            line = " ".join(rng.choice(words) if rng.random() > 0.02 else rng.choice(originals) for _ in range(10))
            parts.append(line)
            size += len(line) + 1
        files[f"pkg{index % 20:02d}/module_{index:04d}.py"] = "\n".join(parts) + "\n"
    return make_project(tmp_path / "proj", files, use_git=False), dictionary


@pytest.mark.slow
def test_obfuscation_time_within_limit(tmp_path: Path) -> None:
    project, dictionary_path = _project(tmp_path)
    dictionary = load_dictionary(dictionary_path)
    git = SubprocessGit()

    started = time.perf_counter()
    report = run_obfuscate([project], tmp_path / "copy", dictionary, git)
    obfuscation = time.perf_counter() - started

    for index in range(0, FILES, 20):
        path = tmp_path / "copy" / f"pkg{index % 20:02d}/module_{index:04d}.py"
        path.write_text(path.read_text(encoding="utf-8") + "def added(): return zz0001q\n", encoding="utf-8")
    started = time.perf_counter()
    run_restore(tmp_path / "copy", "patch", dictionary, git, patch_file=tmp_path / "p.patch")
    restore = time.perf_counter() - started

    replacements = report.counters["replacements"]
    print(f"\nобфускация: {obfuscation:.2f} с, возврат 50 файлов: {restore:.2f} с, замен: {replacements}")
    assert report.counters["copied"] == FILES
    assert obfuscation <= LIMIT_SECONDS  # SC-010
