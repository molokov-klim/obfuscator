"""Поиск строк без учёта регистра: утечки оригиналов и алиасы в другом регистре (спецификация §5.5, §5.7 п. 11).

Без учёта регистра здесь — флаг ``re.IGNORECASE`` (простое сопоставление регистра Unicode); для байтов — только
латинские буквы ASCII.
"""

import bisect
import re
from collections.abc import Iterable
from dataclasses import dataclass

from obfuscator.allow import AllowList
from obfuscator.errors import finding
from obfuscator.models import Finding


@dataclass(frozen=True)
class Match:
    """Находка в тексте.

    Attributes:
        start: Смещение начала в тексте.
        text: Найденное написание (как в тексте).
        line: Номер строки с 1.
    """

    start: int
    text: str
    line: int


class Scanner:
    """Поиск набора строк (по умолчанию без учёта регистра) с перекрытием: проверяется каждая позиция текста."""

    def __init__(self, needles: Iterable[str], *, ignore_case: bool = True) -> None:
        """Создаёт сканер.

        Args:
            needles: Искомые строки; пустые игнорируются.
            ignore_case: Искать без учёта регистра (по умолчанию) или точно.
        """
        flags = re.IGNORECASE if ignore_case else 0
        items = sorted({needle for needle in needles if needle}, key=lambda key: (-len(key), key))
        self._pattern = (
            re.compile("(?=(" + "|".join(re.escape(item) for item in items) + "))", flags) if items else None
        )
        encoded = sorted({item.encode() for item in items}, key=lambda key: (-len(key), key))
        self._bytes_pattern = (
            re.compile(b"(?=(" + b"|".join(re.escape(item) for item in encoded) + b"))", flags) if encoded else None
        )

    def find(self, text: str) -> list[Match]:
        """Находит все вхождения; в одной позиции — самое длинное.

        Args:
            text: Текст.

        Returns:
            Находки в порядке позиций.
        """
        if self._pattern is None:
            return []
        newlines = [index for index, ch in enumerate(text) if ch == "\n"]
        return [
            Match(start=m.start(), text=m.group(1), line=bisect.bisect_left(newlines, m.start()) + 1)
            for m in self._pattern.finditer(text)
        ]

    def find_bytes(self, data: bytes) -> list[bytes]:
        """Находит вхождения UTF-8 байтов строк; регистр игнорируется только для латинских букв ASCII.

        Args:
            data: Байты файла.

        Returns:
            Найденные последовательности байтов в порядке позиций.
        """
        if self._bytes_pattern is None:
            return []
        return [m.group(1) for m in self._bytes_pattern.finditer(data)]


def leak_findings(scanner: Scanner, text: str, path: str, allow: AllowList, code: str) -> list[Finding]:
    """Находки оригиналов в тексте, не разрешённые `.obfallow.toml`.

    Args:
        scanner: Сканер оригиналов.
        text: Текст копии (или новые строки агента).
        path: Путь оригинала относительно корня.
        allow: Допустимые написания.
        code: ``E12`` при обфускации, ``W10`` при возврате.

    Returns:
        Находки с путём, строкой и написанием.
    """
    return [
        finding(code, f"«{m.text}»", path=path, line=m.line, text=m.text)
        for m in scanner.find(text)
        if not allow.allows(m.text, path)
    ]


def path_leak_findings(
    scanner: Scanner, copy_path: str, original_path: str, allow: AllowList, code: str
) -> list[Finding]:
    """Находки оригиналов в пути копии.

    Args:
        scanner: Сканер оригиналов.
        copy_path: Путь копии.
        original_path: Путь оригинала (для сообщения и `.obfallow.toml`).
        allow: Допустимые написания.
        code: ``E12`` или ``W10``.

    Returns:
        Находки без номера строки.
    """
    return [
        finding(code, f"в пути: «{m.text}»", path=original_path, text=m.text)
        for m in scanner.find(copy_path)
        if not allow.allows(m.text, original_path)
    ]


def binary_findings(scanner: Scanner, data: bytes, path: str) -> list[Finding]:
    """Предупреждение W01 об оригинале в бинарном файле: одно на файл, с первым найденным написанием.

    Args:
        scanner: Сканер оригиналов.
        data: Байты файла.
        path: Путь оригинала.

    Returns:
        Ноль или одна находка W01.
    """
    found = scanner.find_bytes(data)
    if not found:
        return []
    text = found[0].decode("utf-8", errors="replace")
    return [finding("W01", f"«{text}»", path=path, text=text)]


def case_mismatch_findings(alias_scanner: Scanner, aliases: frozenset[str], text: str, path: str) -> list[Finding]:
    """Предупреждения W11: алиас в другом регистре — такое вхождение не восстанавливается.

    Args:
        alias_scanner: Сканер алиасов.
        aliases: Точные алиасы.
        text: Новые строки агента.
        path: Путь оригинала.

    Returns:
        Находки W11.
    """
    return [
        finding("W11", f"«{m.text}»", path=path, line=m.line, text=m.text)
        for m in alias_scanner.find(text)
        if m.text not in aliases
    ]
