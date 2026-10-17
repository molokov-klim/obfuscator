"""Регулярное выражение из префиксного дерева строк.

Простая альтернатива ``a|b|c`` из сотен строк проверяет каждую строку в каждой позиции текста: на словаре из 500
непохожих оригиналов это минуты на мегабайты. Выражение из дерева проверяет общий префикс один раз; ветви узла
различаются первым символом, поэтому в каждой позиции подходит не более одной ветви, а жадная необязательная группа
после конечного узла даёт самое длинное совпадение.
"""

import re
from collections.abc import Iterable


class _Node:
    __slots__ = ("children", "terminal")

    def __init__(self) -> None:
        self.children: dict[str, _Node] = {}
        self.terminal = False


def _pattern(node: _Node) -> str:
    branches = [re.escape(char) + _pattern(child) for char, child in sorted(node.children.items())]
    if not branches:
        return ""
    body = branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"
    return f"(?:{body})?" if node.terminal else body


def trie_pattern(keys: Iterable[str]) -> str:
    """Строит выражение, совпадающее с самой длинной из строк в данной позиции.

    Args:
        keys: Непустые строки.

    Returns:
        Текст регулярного выражения; пустая строка, если строк нет.
    """
    root = _Node()
    for key in keys:
        node = root
        for char in key:
            node = node.children.setdefault(char, _Node())
        node.terminal = True
    return _pattern(root)
