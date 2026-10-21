"""Вход, корень и набор файлов (спецификация §5.2; без git и `.obfignore` — §5.8 п. 2)."""

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from obfuscator.allow import ALLOW_FILE
from obfuscator.errors import ObfuscatorError, finding
from obfuscator.gitio import Git
from obfuscator.ignore import IGNORE_FILE, IgnoreRules
from obfuscator.models import Finding

SERVICE_NAMES = frozenset({IGNORE_FILE, ALLOW_FILE})


@dataclass(frozen=True)
class InputSet:
    """Разобранный вход.

    Attributes:
        root: Абсолютный корень.
        inputs: Пути входа относительно корня (``.`` — сам корень), разделитель ``/``.
        git: Вход под git.
        files: Отобранные файлы относительно корня, отсортированы.
        excluded_ignore: Файлы, исключённые `.obfignore`.
        excluded_service: Служебные файлы, исключённые всегда.
        skipped: Предупреждения W03.
    """

    root: Path
    inputs: tuple[str, ...]
    git: bool
    files: tuple[str, ...]
    excluded_ignore: tuple[str, ...] = ()
    excluded_service: tuple[str, ...] = ()
    skipped: tuple[Finding, ...] = field(default=())


def _relative(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return relative if relative else "."


def _is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def find_root(paths: Sequence[Path], git: Git) -> tuple[Path, bool]:
    """Определяет корень и признак git (§5.2 п. 1–3).

    Args:
        paths: Абсолютные существующие пути входа.
        git: Порт git.

    Returns:
        Корень и признак «вход под git».

    Raises:
        ObfuscatorError: E07 — смешение git/не git, разные репозитории, разные диски.
    """
    tops: set[Path | None] = set()
    for path in paths:
        top = git.toplevel(path if path.is_dir() else path.parent)
        tops.add(top.resolve() if top is not None else None)
    if len(tops) > 1:
        if None in tops:
            raise ObfuscatorError.single("E07", "часть путей входа под git, часть — нет")
        raise ObfuscatorError.single("E07", "пути входа принадлежат разным git-репозиториям")
    top = next(iter(tops))
    if top is not None:
        return top, True
    return common_root(paths), False


def common_root(paths: Sequence[Path]) -> Path:
    """Общий предок путей: для файла берётся его каталог, для каталога — он сам (§5.2 п. 3).

    Args:
        paths: Абсолютные существующие пути.

    Returns:
        Корень.

    Raises:
        ObfuscatorError: E07 — пути на разных дисках.
    """
    bases = [str(path if path.is_dir() else path.parent) for path in paths]
    try:
        return Path(os.path.commonpath(bases))
    except ValueError as exc:
        raise ObfuscatorError.single("E07", "пути входа на разных дисках") from exc


def _absolute_existing(paths: Sequence[Path]) -> list[Path]:
    if not paths:
        raise ObfuscatorError.single("E07", "не задан ни один путь")
    absolute: list[Path] = []
    for path in paths:
        if not path.exists():
            raise ObfuscatorError.single("E07", f"путь не существует: {path}")
        absolute.append(path.resolve())
    return absolute


def _is_service(relative: str, protected: Iterable[Path], root: Path) -> bool:
    parts = relative.split("/")
    if ".git" in parts[:-1] or parts[-1] == ".git" or parts[-1] in SERVICE_NAMES:
        return True
    absolute = root / relative
    return any(_is_within(absolute, item) for item in protected)


def resolve_inputs(paths: Sequence[Path], git: Git, *, protected: Sequence[Path] = ()) -> InputSet:
    """Разбирает вход и отбирает файлы.

    Args:
        paths: Пути входа (как переданы пользователем).
        git: Порт git.
        protected: Абсолютные пути, которые никогда не попадают в копию: файл словаря, каталоги копии и состояния.

    Returns:
        Разобранный вход.

    Raises:
        ObfuscatorError: E07 — путь не существует или вход противоречив; E13 — неверный `.obfignore`.
    """
    absolute = _absolute_existing(paths)
    root, is_git = find_root(absolute, git)
    inputs = tuple(sorted({_relative(path, root) for path in absolute}))
    rules = IgnoreRules(root)
    protected_resolved = [item.resolve() for item in protected]

    candidates: set[str] = set()
    skipped: list[Finding] = []
    service: set[str] = set()
    ignored: set[str] = set()

    def consider(relative: str) -> None:
        absolute_path = root / relative
        if _is_service(relative, protected_resolved, root):
            service.add(relative)
        elif absolute_path.is_symlink():
            skipped.append(finding("W03", "символическая ссылка", path=relative))
        elif absolute_path.is_dir():
            skipped.append(finding("W03", "подмодуль git", path=relative))
        elif not absolute_path.is_file():
            return
        elif rules.is_excluded(relative):
            ignored.add(relative)
        else:
            candidates.add(relative)

    if is_git:
        for relative in git.tracked_files(root, inputs):
            consider(relative)
    else:
        for path in absolute:
            if path.is_file() or path.is_symlink():
                consider(_relative(path, root))
                continue
            for directory, dirnames, filenames in os.walk(path):
                base = Path(directory)
                kept: list[str] = []
                for name in sorted(dirnames):
                    relative = _relative(base / name, root)
                    if name == ".git" or _is_service(relative, protected_resolved, root):
                        continue
                    if (base / name).is_symlink():
                        skipped.append(finding("W03", "символическая ссылка", path=relative))
                    elif rules.is_excluded(relative, is_dir=True):
                        ignored.add(relative + "/")
                    else:
                        kept.append(name)
                dirnames[:] = kept
                for name in sorted(filenames):
                    consider(_relative(base / name, root))

    return InputSet(
        root=root,
        inputs=inputs,
        git=is_git,
        files=tuple(sorted(candidates)),
        excluded_ignore=tuple(sorted(ignored)),
        excluded_service=tuple(sorted(service)),
        skipped=tuple(sorted(skipped, key=lambda item: item.path or "")),
    )


def resolve_plain_inputs(paths: Sequence[Path], *, protected: Sequence[Path] = ()) -> InputSet:
    """Разбирает вход деобфускации: все обычные файлы путей, без git и `.obfignore` (§5.8 п. 2).

    Args:
        paths: Пути входа (как переданы пользователем).
        protected: Абсолютные пути, которые пропускаются: файл словаря, каталог результата.

    Returns:
        Разобранный вход (``git`` всегда ``False``, ``excluded_ignore`` пуст).

    Raises:
        ObfuscatorError: E07 — путь не существует или пути на разных дисках.
    """
    absolute = _absolute_existing(paths)
    root = common_root(absolute)
    inputs = tuple(sorted({_relative(path, root) for path in absolute}))
    protected_resolved = [item.resolve() for item in protected]
    candidates: set[str] = set()
    skipped: list[Finding] = []
    service: set[str] = set()

    def is_protected(path: Path) -> bool:
        return any(_is_within(path, item) for item in protected_resolved)

    def consider(path: Path) -> None:
        relative = _relative(path, root)
        if path.is_symlink():
            skipped.append(finding("W03", "символическая ссылка", path=relative))
        elif is_protected(path):
            service.add(relative)
        elif path.is_file():
            candidates.add(relative)

    for path in absolute:
        if not path.is_dir():
            consider(path)
            continue
        for directory, dirnames, filenames in os.walk(path):
            base = Path(directory)
            kept: list[str] = []
            for name in sorted(dirnames):
                child = base / name
                if name == ".git":
                    continue
                if child.is_symlink():
                    skipped.append(finding("W03", "символическая ссылка", path=_relative(child, root)))
                elif is_protected(child):
                    service.add(_relative(child, root) + "/")
                else:
                    kept.append(name)
            dirnames[:] = kept
            for name in sorted(filenames):
                consider(base / name)

    return InputSet(
        root=root,
        inputs=inputs,
        git=False,
        files=tuple(sorted(candidates)),
        excluded_service=tuple(sorted(service)),
        skipped=tuple(sorted(skipped, key=lambda item: item.path or "")),
    )
