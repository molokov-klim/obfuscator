"""Прямая и обратная замена за один проход (спецификация §5.3)."""

from collections import Counter
from collections.abc import Iterable, Mapping

from obfuscator.matcher import Matcher
from obfuscator.models import Rule


class Replacer:
    """Замена строк по таблице «источник → цель».

    Кандидаты ищутся регулярным выражением из префиксного дерева (``trie.py``, ``matcher.py``): в каждой позиции
    берётся самый длинный подходящий источник; источники «по словам» подходят только на границе слова (FR-071).
    Результат не зависит от порядка правил (NFR-010), время линейно от длины текста (NFR-020). Регистр учитывается.
    """

    def __init__(self, table: Mapping[str, str], words: Iterable[str] = ()) -> None:
        """Создаёт заменитель.

        Args:
            table: Источник → цель; пустые источники не допускаются.
            words: Источники, которые заменяются только на границе слова.

        Raises:
            ValueError: Пустой источник или источник «по словам» вне таблицы.
        """
        if "" in table:
            raise ValueError("пустой источник замены")
        self.table: dict[str, str] = dict(table)
        self.words = frozenset(words)
        if not self.words <= self.table.keys():
            raise ValueError("источник «по словам» отсутствует в таблице")
        self._matcher = Matcher({key: key in self.words for key in self.table})

    def replace(self, text: str) -> tuple[str, Counter[str]]:
        """Заменяет все вхождения источников.

        Args:
            text: Исходный текст.

        Returns:
            Текст после замены и счётчик замен по источникам.
        """
        counts: Counter[str] = Counter()
        parts: list[str] = []
        position = 0
        for hit in self._matcher.iter_hits(text):
            parts.append(text[position : hit.start])
            parts.append(self.table[hit.key])
            counts[hit.key] += 1
            position = hit.end
        if not counts:
            return text, counts
        parts.append(text[position:])
        return "".join(parts), counts

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
    items = list(rules)
    return Replacer({rule.original: rule.alias for rule in items}, (rule.original for rule in items if rule.word))


def backward(rules: Iterable[Rule]) -> Replacer:
    """Заменитель «алиас → оригинал».

    Args:
        rules: Проверенные правила (алиасы уникальны, E04).

    Returns:
        Заменитель обратной замены.
    """
    items = list(rules)
    return Replacer({rule.alias: rule.original for rule in items}, (rule.alias for rule in items if rule.word))
