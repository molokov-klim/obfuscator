"""Поиск строк без учёта регистра: утечки оригиналов и алиасы в другом регистре (спецификация §5.5, §5.7 п. 11).

Без учёта регистра здесь — сравнение после ``str.lower()`` (для байтов — только латинские буквы ASCII): текст и
искомые строки приводятся к нижнему регистру, и ищется точное совпадение. Это в разы быстрее ``re.IGNORECASE`` на
больших словарях. Если ``lower()`` меняет длину текста (редкие символы вроде «İ»), используется ``re.IGNORECASE``.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from obfuscator.allow import AllowList
from obfuscator.errors import finding
from obfuscator.models import Finding
from obfuscator.trie import trie_pattern


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
        self._ignore_case = ignore_case
        items = {needle for needle in needles if needle}
        keys = {item.lower() for item in items} if ignore_case else items
        pattern = trie_pattern(keys)
        self._pattern = re.compile(pattern) if keys else None
        self._fallback = re.compile(pattern, re.IGNORECASE) if keys and ignore_case else None
        # Байты — через latin-1: каждый байт становится одним символом, выражение кодируется обратно без потерь.
        byte_keys = {item.encode().lower() if ignore_case else item.encode() for item in items}
        byte_pattern = trie_pattern(key.decode("latin-1") for key in byte_keys)
        self._bytes_pattern = re.compile(byte_pattern.encode("latin-1")) if byte_keys else None

    def find(self, text: str) -> list[Match]:
        """Находит все вхождения, в том числе перекрывающиеся; в одной позиции — самое длинное.

        Args:
            text: Текст.

        Returns:
            Находки в порядке позиций.
        """
        if self._pattern is None:
            return []
        pattern, haystack = self._pattern, text
        if self._ignore_case:
            lowered = text.lower()
            if len(lowered) == len(text):
                haystack = lowered
            else:
                assert self._fallback is not None
                pattern = self._fallback
        matches: list[Match] = []
        line, previous, position = 1, 0, 0
        while (m := pattern.search(haystack, position)) is not None:
            start = m.start()
            line += text.count("\n", previous, start)
            previous = start
            matches.append(Match(start=start, text=text[start : m.end()], line=line))
            position = start + 1
        return matches

    def find_bytes(self, data: bytes) -> list[bytes]:
        """Находит вхождения UTF-8 байтов строк; регистр игнорируется только для латинских букв ASCII.

        Args:
            data: Байты файла.

        Returns:
            Найденные последовательности байтов в порядке позиций.
        """
        if self._bytes_pattern is None:
            return []
        haystack = data.lower() if self._ignore_case else data
        found: list[bytes] = []
        position = 0
        while (m := self._bytes_pattern.search(haystack, position)) is not None:
            found.append(data[m.start() : m.end()])
            position = m.start() + 1
        return found


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
