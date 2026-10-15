"""Файловые операции: деревья файлов, хэши, атомарная замена каталогов."""

import os
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

from obfuscator.state import sha256_hex


def write_tree(directory: Path, files: Mapping[str, bytes]) -> None:
    """Записывает файлы в каталог.

    Args:
        directory: Каталог (создаётся).
        files: Путь относительно каталога (разделитель ``/``) → байты.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for relative, data in files.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def read_tree(directory: Path) -> dict[str, bytes]:
    """Читает все обычные файлы каталога, пропуская каталоги ``.git``.

    Args:
        directory: Каталог.

    Returns:
        Путь относительно каталога (разделитель ``/``) → байты.
    """
    files: dict[str, bytes] = {}
    for current, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(name for name in dirnames if name != ".git")
        base = Path(current)
        for name in filenames:
            path = base / name
            if path.is_file() and not path.is_symlink():
                files[path.relative_to(directory).as_posix()] = path.read_bytes()
    return files


def hash_tree(directory: Path) -> dict[str, str]:
    """Хэши всех файлов каталога.

    Args:
        directory: Каталог.

    Returns:
        Путь → SHA-256.
    """
    return {relative: sha256_hex(data) for relative, data in read_tree(directory).items()}


def is_empty_dir(path: Path) -> bool:
    """Проверяет, что путь — пустой каталог.

    Args:
        path: Путь.

    Returns:
        ``True`` для существующего пустого каталога.
    """
    return path.is_dir() and not any(path.iterdir())


def make_staging(target: Path) -> Path:
    """Создаёт временный каталог рядом с целевым (та же файловая система — переименование атомарно).

    Args:
        target: Будущий путь каталога.

    Returns:
        Путь временного каталога.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent))


def remove_tree(path: Path) -> None:
    """Удаляет каталог, если он есть.

    Args:
        path: Каталог.
    """
    if path.exists():
        shutil.rmtree(path)


def swap_into_place(pairs: list[tuple[Path, Path]]) -> None:
    """Ставит подготовленные каталоги на место целевых; старые удаляются после успешной замены всех.

    Если замена прерывается ошибкой, уже заменённые целевые каталоги возвращаются на место.

    Args:
        pairs: Пары (подготовленный каталог, целевой путь).

    Raises:
        OSError: Ошибка файловой системы (после отката).
    """
    moved_aside: list[tuple[Path, Path]] = []
    placed: list[Path] = []
    try:
        for staged, target in pairs:
            if target.exists():
                aside = Path(tempfile.mkdtemp(prefix=f".{target.name}.old-", dir=target.parent))
                aside.rmdir()
                os.replace(target, aside)
                moved_aside.append((aside, target))
            os.replace(staged, target)
            placed.append(target)
    except OSError:
        for target in placed:
            remove_tree(target)
        for aside, target in moved_aside:
            os.replace(aside, target)
        raise
    for aside, _ in moved_aside:
        remove_tree(aside)
