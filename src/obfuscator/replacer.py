"""Прямая и обратная замена за один проход (спецификация §5.3)."""

import re
from collections import Counter
from collections.abc import Iterable, Mapping

from obfuscator.models import Rule
from obfuscator.trie import trie_pattern


class Replacer:
    """Замена строк по таблице «источник → цель» одним регулярным выражением.

    Выражение строится из префиксного дерева источников (``trie.py``): в каждой позиции берётся самый длинный
    подходящий источник, результат не зависит от порядка правил (NFR-010), время — линейно от длины текста
    (NFR-020). Регистр учитывается, границы слов — нет.
    """

    def __init__(self, table: Mapping[str, str]) -> None:
        """Создаёт заменитель.

        Args:
            table: Источник → цель; пустые источники не допускаются.

        Raises:
            ValueError: Пустой источник.
        """
        if "" in table:
            raise ValueError("пустой источник замены")
        self.table: dict[str, str] = dict(table)
        self._pattern = re.compile(trie_pattern(self.table)) if self.table else None

    def replace(self, text: str) -> tuple[str, Counter[str]]:
        """Заменяет все вхождения источников.

        Args:
            text: Исходный текст.

        Returns:
            Текст после замены и счётчик замен по источникам.
        """
        counts: Counter[str] = Counter()
        if self._pattern is None:
            return text, counts

        def substitute(match: re.Match[str]) -> str:
            source = match.group(0)
            counts[source] += 1
            return self.table[source]

        return self._pattern.sub(substitute, text), counts

    def apply(self, text: str) -> str:
        """Заменяет все вхождения источников без подсчёта.

        Args:
            text: Исходный текст.

        Returns:
            Текст после замены.
        """
        return self.replace(text)[0]


def forward(rules: Iterable[Rule]) -> Replacer:
    """Заменитель «оригинал → алиас».

    Args:
        rules: Проверенные правила.

    Returns:
        Заменитель прямой замены.
    """
    return Replacer({rule.original: rule.alias for rule in rules})


def backward(rules: Iterable[Rule]) -> Replacer:
    """Заменитель «алиас → оригинал».

    Args:
        rules: Проверенные правила (алиасы уникальны, E04).

    Returns:
        Заменитель обратной замены.
    """
    return Replacer({rule.alias: rule.original for rule in rules})
