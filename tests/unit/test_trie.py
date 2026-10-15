import random
import re

import pytest

from obfuscator.trie import trie_pattern


def _naive_longest(keys: list[str], text: str) -> list[tuple[int, str]]:
    ordered = sorted(keys, key=lambda key: (-len(key), key))
    pattern = re.compile("|".join(re.escape(key) for key in ordered))
    return [(m.start(), m.group(0)) for m in pattern.finditer(text)]


def _trie(keys: list[str], text: str) -> list[tuple[int, str]]:
    return [(m.start(), m.group(0)) for m in re.finditer(trie_pattern(keys), text)]


@pytest.mark.parametrize(
    ("keys", "text"),
    [
        (["Pepelac", "PepelacBig", "Pep"], "PepelacBig Pepelac Pepe Pep"),
        (["abc", "bcdef"], "abcdef"),
        (["a.b*", "a"], "a.b* axbb a"),
        (["x"], "xxx"),
        (["тест", "тестер"], "тестер тест"),
    ],
)
def test_matches_naive_longest_alternation(keys: list[str], text: str) -> None:
    assert _trie(keys, text) == _naive_longest(keys, text)


def test_random_equivalence() -> None:
    rng = random.Random(7)
    for _ in range(500):
        keys = list({"".join(rng.choice("abc") for _ in range(rng.randint(1, 4))) for _ in range(rng.randint(1, 6))})
        text = "".join(rng.choice("abcd") for _ in range(rng.randint(0, 40)))
        assert _trie(keys, text) == _naive_longest(keys, text), (keys, text)


def test_empty() -> None:
    assert trie_pattern([]) == ""
