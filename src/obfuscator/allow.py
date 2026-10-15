"""Допустимые написания `.obfallow.toml` (спецификация §3.4)."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

import pathspec

from obfuscator.errors import ObfuscatorError
from obfuscator.narrow import as_list, as_table

ALLOW_FILE = ".obfallow.toml"


@dataclass(frozen=True)
class AllowEntry:
    """Запись допустимого написания.

    Attributes:
        text: Точное написание (с учётом регистра).
        files: Шаблоны путей в синтаксисе `.gitignore`; ``None`` — везде.
    """

    text: str
    files: tuple[str, ...] | None


class AllowList:
    """Набор допустимых написаний проекта."""

    def __init__(self, entries: tuple[AllowEntry, ...] = ()) -> None:
        """Создаёт набор.

        Args:
            entries: Записи в порядке файла.
        """
        self.entries = entries
        self._specs: list[tuple[str, pathspec.GitIgnoreSpec | None]] = [
            (entry.text, None if entry.files is None else pathspec.GitIgnoreSpec.from_lines(entry.files))
            for entry in entries
        ]

    def allows(self, text: str, path: str) -> bool:
        """Проверяет, разрешена ли находка.

        Args:
            text: Найденное написание.
            path: Путь оригинала относительно корня, разделитель ``/``.

        Returns:
            ``True``, если есть запись с тем же написанием, чьи шаблоны покрывают путь (или шаблонов нет).
        """
        for allowed_text, spec in self._specs:
            if allowed_text == text and (spec is None or spec.match_file(path)):
                return True
        return False


def load_allow(root: Path) -> AllowList:
    """Читает `.obfallow.toml` из корня; если файла нет — пустой набор.

    Args:
        root: Корень входа.

    Returns:
        Набор допустимых написаний.

    Raises:
        ObfuscatorError: E13 — файл не читается или неверный формат.
    """
    path = root / ALLOW_FILE
    if not path.exists():
        return AllowList()
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ObfuscatorError.single("E13", f"не удалось прочитать {ALLOW_FILE}: {exc.strerror or exc}") from exc
    return parse_allow(data, ALLOW_FILE)


def parse_allow(data: bytes, source: str) -> AllowList:
    """Разбирает `.obfallow.toml`.

    Args:
        data: Байты файла.
        source: Имя источника для сообщений.

    Returns:
        Набор допустимых написаний.

    Raises:
        ObfuscatorError: E13 — неверный формат.
    """

    def fail(detail: str) -> ObfuscatorError:
        return ObfuscatorError.single("E13", f"{source}: {detail}")

    try:
        document = tomllib.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise fail("файл не в UTF-8") from exc
    except tomllib.TOMLDecodeError as exc:
        raise fail(f"не TOML: {exc}") from exc

    extra = sorted(key for key in document if key != "allow")
    if extra:
        raise fail(f"неизвестные ключи верхнего уровня: {', '.join(extra)}")
    if "allow" not in document:
        return AllowList()
    items = as_list(document["allow"])
    if items is None:
        raise fail("allow должен быть массивом таблиц [[allow]]")

    entries: list[AllowEntry] = []
    for number, item in enumerate(items, start=1):
        table = as_table(item)
        if table is None:
            raise fail(f"запись {number}: ожидается таблица [[allow]]")
        unknown = sorted(key for key in table if key not in ("text", "files"))
        if unknown:
            raise fail(f"запись {number}: неизвестные поля: {', '.join(unknown)}")
        text = table.get("text")
        if not isinstance(text, str) or not text or "\n" in text or "\r" in text:
            raise fail(f"запись {number}: text — непустая строка без переводов строк")
        files: tuple[str, ...] | None = None
        if "files" in table:
            raw = as_list(table["files"])
            if not raw or not all(isinstance(p, str) and p for p in raw):
                raise fail(f"запись {number}: files — непустой список непустых строк")
            files = tuple(str(p) for p in raw)
        entries.append(AllowEntry(text=text, files=files))
    return AllowList(tuple(entries))
