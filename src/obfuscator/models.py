"""Модели данных (спецификация §4.1.1–4.1.2)."""

from dataclasses import dataclass, field
from typing import Literal

FileKind = Literal["text", "binary"]
Command = Literal["obfuscate", "restore"]


@dataclass(frozen=True)
class Rule:
    """Правило словаря.

    Attributes:
        original: Оригинал, сравнивается с учётом регистра.
        alias: Алиас, которым оригинал заменяется в копии.
    """

    original: str
    alias: str


@dataclass(frozen=True)
class FileEntry:
    """Файл точки отсчёта.

    Attributes:
        original_path: Путь оригинала относительно корня, разделитель ``/``.
        copy_path: Путь в копии относительно каталога копии, разделитель ``/``.
        kind: ``text`` или ``binary``.
        original_sha256: Хэш содержимого оригинала.
        copy_sha256: Хэш содержимого копии.
    """

    original_path: str
    copy_path: str
    kind: FileKind
    original_sha256: str
    copy_sha256: str


@dataclass(frozen=True)
class Finding:
    """Ошибка или предупреждение.

    Attributes:
        code: Код из спецификации §7 (``E12``, ``W10``, …).
        message: Сообщение для пользователя.
        path: Путь оригинала относительно корня, если применимо.
        line: Номер строки с 1, если применимо.
        text: Найденное написание, если применимо.
    """

    code: str
    message: str
    path: str | None = None
    line: int | None = None
    text: str | None = None


@dataclass
class Report:
    """Отчёт обфускации или возврата.

    Attributes:
        command: Сценарий.
        ok: ``True``, если отказа не было.
        errors: Ошибки (E-коды).
        warnings: Предупреждения (W-коды).
        counters: Счётчики сводки (§6.1).
        per_rule: Оригинал → число замен.
        per_file: Путь оригинала → число замен.
        files: Категория → пути оригинала.
    """

    command: Command
    ok: bool = True
    errors: list[Finding] = field(default_factory=list[Finding])
    warnings: list[Finding] = field(default_factory=list[Finding])
    counters: dict[str, int] = field(default_factory=dict[str, int])
    per_rule: dict[str, int] = field(default_factory=dict[str, int])
    per_file: dict[str, int] = field(default_factory=dict[str, int])
    files: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
