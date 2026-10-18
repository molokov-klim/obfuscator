"""Поиск строк без учёта регистра: утечки оригиналов и алиасы в другом регистре (спецификация §5.5, §5.7 п. 11).

Без учёта регистра — сравнение после ``str.lower()``: текст и искомые строки приводятся к нижнему регистру
посимвольно (символ, который при этом превращается в несколько, остаётся как есть — длина текста сохраняется), и
ищется точное совпадение. Для байтов регистр игнорируется только у латинских букв ASCII. Строки «по словам»
находятся только на границе слова (FR-071, FR-072); граница проверяется по исходному регистру текста.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from obfuscator.allow import AllowList
from obfuscator.errors import finding
from obfuscator.matcher import Matcher
from obfuscator.models import Finding, Rule


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


def _lower_same_length(text: str) -> str:
    lowered = text.lower()
    if len(lowered) == len(text):
        return lowered
    return "".join(low if len(low := char.lower()) == 1 else char for char in text)


def _keys(substrings: Iterable[str], words: Iterable[str], ignore_case: bool) -> dict[str, bool]:
    keys: dict[str, bool] = {}
    for needle in words:
        if needle:
            keys[needle.lower() if ignore_case else needle] = True
    for needle in substrings:
        if needle:
            keys[needle.lower() if ignore_case else needle] = False  # подстрока строже: находит больше
    return keys


class Scanner:
    """Поиск набора строк (по умолчанию без учёта регистра) с перекрытием: проверяется каждая позиция текста."""

    def __init__(self, needles: Iterable[str], *, words: Iterable[str] = (), ignore_case: bool = True) -> None:
        """Создаёт сканер.

        Args:
            needles: Строки, которые ищутся везде (правила подстроки); пустые игнорируются.
            words: Строки, которые ищутся только на границе слова (правила по словам).
            ignore_case: Искать без учёта регистра (по умолчанию) или точно.
        """
        self._ignore_case = ignore_case
        items = list(needles)
        word_items = list(words)
        self._matcher = Matcher(_keys(items, word_items, ignore_case), ignore_case=ignore_case)
        byte_keys: dict[str, bool] = {}
        for key, word in _keys(items, word_items, False).items():
            encoded = key.encode()
            byte_keys[(encoded.lower() if ignore_case else encoded).decode("latin-1")] = word
        self._bytes_matcher = Matcher(byte_keys, ascii_only=True, ignore_case=ignore_case)

    @classmethod
    def originals(cls, rules: Iterable[Rule]) -> "Scanner":
        """Сканер оригиналов словаря без учёта регистра.

        Args:
            rules: Правила.

        Returns:
            Сканер.
        """
        items = list(rules)
        return cls((r.original for r in items if not r.word), words=(r.original for r in items if r.word))

    @classmethod
    def aliases(cls, rules: Iterable[Rule], *, ignore_case: bool) -> "Scanner":
        """Сканер алиасов словаря.

        Args:
            rules: Правила.
            ignore_case: Искать без учёта регистра.

        Returns:
            Сканер.
        """
        items = list(rules)
        return cls(
            (r.alias for r in items if not r.word),
            words=(r.alias for r in items if r.word),
            ignore_case=ignore_case,
        )

    def find(self, text: str) -> list[Match]:
        """Находит все вхождения, в том числе перекрывающиеся; в одной позиции — самое длинное.

        Args:
            text: Текст.

        Returns:
            Находки в порядке позиций.
        """
        haystack = _lower_same_length(text) if self._ignore_case else text
        matches: list[Match] = []
        line, previous = 1, 0
        for hit in self._matcher.iter_hits(haystack, text, overlapping=True):
            line += text.count("\n", previous, hit.start)
            previous = hit.start
            matches.append(Match(start=hit.start, text=text[hit.start : hit.end], line=line))
        return matches

    def find_bytes(self, data: bytes) -> list[bytes]:
        """Находит вхождения UTF-8 байтов строк; регистр игнорируется только для латинских букв ASCII.

        Args:
            data: Байты файла.

        Returns:
            Найденные последовательности байтов в порядке позиций.
        """
        text = data.decode("latin-1")
        haystack = data.lower().decode("latin-1") if self._ignore_case else text
        return [data[hit.start : hit.end] for hit in self._bytes_matcher.iter_hits(haystack, text, overlapping=True)]


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
