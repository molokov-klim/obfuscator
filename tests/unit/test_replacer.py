import pytest

from obfuscator.models import Rule
from obfuscator.replacer import Replacer, backward, forward

RULES = [Rule("Pepelac", "Zqv"), Rule("PepelacBig", "Wmr"), Rule("pepelac", "zqv")]


def test_longest_original_wins_at_same_position() -> None:
    assert forward(RULES).apply("PepelacBig Pepelac") == "Wmr Zqv"


def test_replaces_inside_words() -> None:
    assert forward(RULES).apply("MyPepelacClient_pepelac2") == "MyZqvClient_zqv2"


def test_case_sensitive() -> None:
    assert forward(RULES).apply("PEPELAC") == "PEPELAC"


def test_counts_per_source() -> None:
    text, counts = forward(RULES).replace("Pepelac pepelac Pepelac PepelacBig")
    assert text == "Zqv zqv Zqv Wmr"
    assert counts == {"Pepelac": 2, "pepelac": 1, "PepelacBig": 1}


def test_rule_order_does_not_matter() -> None:
    text = "PepelacBig_Pepelac"
    assert forward(RULES).apply(text) == forward(list(reversed(RULES))).apply(text)


def test_backward_restores() -> None:
    text = "PepelacBig/Pepelac\r\npepelac"
    assert backward(RULES).apply(forward(RULES).apply(text)) == text


def test_special_regex_characters_are_literal() -> None:
    assert Replacer({"a.b*": "X"}).apply("a.b* axbb") == "X axbb"


def test_overlapping_sources_take_leftmost() -> None:
    assert Replacer({"abc": "1", "bcdef": "2"}).apply("abcdef") == "1def"


def test_empty_table_returns_text() -> None:
    assert Replacer({}).replace("abc") == ("abc", {})


def test_empty_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="пустой"):
        Replacer({"": "x"})
