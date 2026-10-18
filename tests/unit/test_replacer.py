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


WORDS = [
    Rule("sim", "qx", word=True),
    Rule("Sim", "Qx", word=True),
    Rule("SIM", "QX", word=True),
    Rule("Pepelac", "Zqv"),
]


def test_word_rules_sc015_examples() -> None:
    text = "sim-x _sim# sim2 sim_client simClient MySim SimRunner SIM_X | simple assimilate SIMPLE Simulator"
    expected = "qx-x _qx# qx2 qx_client qxClient MyQx QxRunner QX_X | simple assimilate SIMPLE Simulator"
    assert forward(WORDS).apply(text) == expected
    assert backward(WORDS).apply(expected) == text


def test_word_and_substring_rules_together() -> None:
    text = "PepelacSim sim.Pepelac"
    assert forward(WORDS).apply(text) == "ZqvQx qx.Zqv"


def test_word_alias_inside_word_is_not_restored() -> None:
    assert backward(WORDS).apply("qxz and qx") == "qxz and sim"


def test_words_must_be_in_table() -> None:
    with pytest.raises(ValueError, match="по словам"):
        Replacer({"a": "b"}, words=["c"])
