"""Поиск набора строк с правилами подстроки и правилами по словам (спецификация §5.3, решение 11).

Кандидаты ищутся регулярными выражениями из префиксного дерева (``trie.py``): строки подстроки — одним выражением,
строки «по словам» — другим, окружённым проверками границы (классы букв Unicode строятся один раз). В позиции
кандидата код обходит дерево всех строк и берёт самую длинную, для которой граница выполнена точно
(``str.isalpha``/``islower``/``isupper``). Выражения отсекают почти все позиции, где граница заведомо не выполнена,
поэтому код работает только в редких местах.
"""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cache

from obfuscator.trie import trie_pattern

_NON_BMP = "\\U00010000-\\U0010ffff"


def char_kind(char: str) -> str:
    """Вид символа для правил по словам: ``lower``, ``upper``, ``letter`` (буква без регистра) или ``other``.

    Args:
        char: Один символ.

    Returns:
        Вид символа.
    """
    if not char.isalpha():
        return "other"
    if char.islower():
        return "lower"
    if char.isupper():
        return "upper"
    return "letter"


def _is_letter(char: str, ascii_only: bool) -> bool:
    return char.isalpha() and (char.isascii() or not ascii_only)


def left_boundary(text: str, start: int, *, ascii_only: bool = False) -> bool:
    """Граница слева от вхождения, начинающегося в ``start`` (FR-071).

    Args:
        text: Текст с исходным регистром.
        start: Начало вхождения.
        ascii_only: Буквами считать только латиницу ASCII (поиск в байтах).

    Returns:
        ``True``, если слева начало текста, не буква или переход строчная → заглавная.
    """
    if start == 0:
        return True
    previous, current = text[start - 1], text[start]
    if not _is_letter(previous, ascii_only):
        return True
    return previous.islower() and current.isupper()


def right_boundary(text: str, end: int, *, ascii_only: bool = False) -> bool:
    """Граница справа от вхождения, кончающегося перед ``end`` (FR-071).

    Args:
        text: Текст с исходным регистром.
        end: Позиция сразу после вхождения.
        ascii_only: Буквами считать только латиницу ASCII (поиск в байтах).

    Returns:
        ``True``, если справа конец текста, не буква или переход строчная → заглавная.
    """
    if end == len(text):
        return True
    last, following = text[end - 1], text[end]
    if not _is_letter(following, ascii_only):
        return True
    return last.islower() and following.isupper()


def _ranges(codes: list[int]) -> str:
    parts: list[str] = []
    start = previous = -2
    for code in codes:
        if code != previous + 1:
            if start >= 0:
                parts.append(f"\\u{start:04x}-\\u{previous:04x}")
            start = code
        previous = code
    if start >= 0:
        parts.append(f"\\u{start:04x}-\\u{previous:04x}")
    return "".join(parts)


@cache
def _letter_classes(ascii_only: bool) -> tuple[str, str, str]:
    """Классы символов «буква», «строчная», «заглавная» для регулярных выражений.

    Для Unicode — по плоскости BMP; символы вне неё выражения пропускают как возможную границу, точная проверка —
    в коде.
    """
    if ascii_only:
        return "A-Za-z", "a-z", "A-Z"
    alpha: list[int] = []
    lower: list[int] = []
    upper: list[int] = []
    for code in range(0x10000):
        char = chr(code)
        if char.isalpha():
            alpha.append(code)
            if char.islower():
                lower.append(code)
            elif char.isupper():
                upper.append(code)
    return _ranges(alpha), _ranges(lower), _ranges(upper)


def _boundary_patterns(ascii_only: bool) -> tuple[str, str]:
    alpha, lower, upper = _letter_classes(ascii_only)
    camel = f"(?<=[{lower}])(?=[{upper}])"
    if ascii_only:
        return f"(?-i:(?<![{alpha}])|{camel})", f"(?-i:(?![{alpha}])|{camel})"
    left = f"(?-i:(?<![{alpha}])|{camel}|(?<=[{_NON_BMP}])|(?=[{_NON_BMP}]))"
    right = f"(?-i:(?![{alpha}])|{camel}|(?<=[{_NON_BMP}])|(?=[{_NON_BMP}]))"
    return left, right


class _Node:
    __slots__ = ("children", "key", "word")

    def __init__(self) -> None:
        self.children: dict[str, _Node] = {}
        self.key: str | None = None
        self.word = False


@dataclass(frozen=True)
class Hit:
    """Найденное вхождение.

    Attributes:
        start: Начало в тексте.
        end: Позиция сразу после вхождения.
        key: Подошедшая строка набора (в нижнем регистре, если поиск без учёта регистра).
    """

    start: int
    end: int
    key: str


class Matcher:
    """Набор строк: строка → признак «только на границе слова»."""

    def __init__(self, keys: Mapping[str, bool], *, ascii_only: bool = False, ignore_case: bool = False) -> None:
        """Создаёт набор.

        Args:
            keys: Строка → ``True`` для правила по словам, ``False`` для правила подстроки; пустые строки игнорируются.
                При ``ignore_case`` строки должны быть уже в нижнем регистре.
            ascii_only: Границы считать по латинице ASCII (поиск в байтах через latin-1).
            ignore_case: Искать без учёта регистра: ``iter_hits`` получает текст в нижнем регистре и исходный текст.
        """
        self._ascii_only = ascii_only
        self._root = _Node()
        clean = {key: word for key, word in keys.items() if key}
        for key, word in clean.items():
            node = self._root
            for char in key:
                node = node.children.setdefault(char, _Node())
            node.key = key
            node.word = word
        substrings = [key for key, word in clean.items() if not word]
        words = [key for key, word in clean.items() if word]
        self._sub_pattern = re.compile(trie_pattern(substrings)) if substrings else None
        self._word_pattern: re.Pattern[str] | None = None
        if words:
            left, right = _boundary_patterns(ascii_only)
            flags = (re.IGNORECASE if ignore_case else 0) | (re.ASCII if ascii_only else 0)
            # Дешёвая проверка первого символа отсекает почти все позиции до дорогих проверок границы.
            first = "".join(sorted({re.escape(word[0]) for word in words}))
            self._word_pattern = re.compile(f"(?=[{first}]){left}(?:{trie_pattern(words)}){right}", flags)

    def _best_at(self, haystack: str, text: str, start: int) -> Hit | None:
        node = self._root
        best: Hit | None = None
        position = start
        while position < len(haystack):
            child = node.children.get(haystack[position])
            if child is None:
                break
            node = child
            position += 1
            if node.key is None:
                continue
            if not node.word or (
                left_boundary(text, start, ascii_only=self._ascii_only)
                and right_boundary(text, position, ascii_only=self._ascii_only)
            ):
                best = Hit(start=start, end=position, key=node.key)
        return best

    def iter_hits(self, haystack: str, text: str | None = None, *, overlapping: bool = False) -> Iterator[Hit]:
        """Перебирает вхождения слева направо.

        Args:
            haystack: Где искать строки (для поиска без учёта регистра — текст в нижнем регистре той же длины).
            text: Тот же текст в исходном регистре (границы, строки «по словам»); ``None`` — совпадает с ``haystack``.
            overlapping: Искать с каждой позиции (сканер) или продолжать после найденного (замена).

        Yields:
            Вхождения; в каждой позиции — самое длинное допустимое.
        """
        source = haystack if text is None else text
        searches: list[tuple[re.Pattern[str], str]] = []
        if self._sub_pattern is not None:
            searches.append((self._sub_pattern, haystack))
        if self._word_pattern is not None:
            searches.append((self._word_pattern, source))
        upcoming: list[int | None] = [-1] * len(searches)
        position = 0
        while True:
            for index, (pattern, target) in enumerate(searches):
                cached = upcoming[index]
                if cached is not None and cached < position:
                    found = pattern.search(target, position)
                    upcoming[index] = found.start() if found is not None else None
            starts = [start for start in upcoming if start is not None]
            if not starts:
                return
            start = min(starts)
            hit = self._best_at(haystack, source, start)
            if hit is None:
                position = start + 1
                continue
            yield hit
            position = start + 1 if overlapping else hit.end
