from pathlib import Path

import pytest

from obfuscator.dictionary import (
    ENV_DICTIONARY,
    load_dictionary,
    parse_dictionary,
    resolve_dictionary_path,
    validate_rules,
)
from obfuscator.errors import ObfuscatorError
from obfuscator.models import Rule

EXAMPLE = Path(__file__).resolve().parents[2] / "dictionary.example.toml"


def _codes(error: ObfuscatorError) -> list[str]:
    return [f.code for f in error.findings]


def _rules(*pairs: tuple[str, str]) -> list[Rule]:
    return [Rule(original=o, alias=a) for o, a in pairs]


def test_example_dictionary_is_valid() -> None:
    dictionary = load_dictionary(EXAMPLE)
    assert Rule("Pepelac", "Zqv") in dictionary.rules
    assert len(dictionary.sha256) == 64


def test_rules_keep_file_order() -> None:
    rules = parse_dictionary(b'[rules]\n"b" = "x1"\n"a" = "x2"\n', "t")
    assert [r.original for r in rules] == ["b", "a"]


def test_sha256_changes_with_content(tmp_path: Path) -> None:
    path = tmp_path / "d.toml"
    path.write_bytes(b'[rules]\n"a" = "x1"\n')
    first = load_dictionary(path).sha256
    path.write_bytes(b'[rules]\n"a" = "x2"\n')
    assert load_dictionary(path).sha256 != first


@pytest.mark.parametrize(
    "content",
    [
        b"not = [toml",
        b"[other]\n",
        b'rules = "x"\n',
        b'[rules]\n"a" = 1\n',
        b'[rules]\n"a" = "x"\n[extra]\n',
        b'[rules]\n"a" = "x"\n"a" = "y"\n',
        '[rules]\n"a" = "x"\n'.encode("utf-16"),
    ],
)
def test_bad_format_is_e01(content: bytes) -> None:
    with pytest.raises(ObfuscatorError) as info:
        parse_dictionary(content, "t")
    assert _codes(info.value) == ["E01"]


def test_missing_file_is_e01(tmp_path: Path) -> None:
    with pytest.raises(ObfuscatorError) as info:
        load_dictionary(tmp_path / "nope.toml")
    assert _codes(info.value) == ["E01"]


def test_empty_rules_is_e02(tmp_path: Path) -> None:
    path = tmp_path / "d.toml"
    path.write_bytes(b"[rules]\n")
    with pytest.raises(ObfuscatorError) as info:
        load_dictionary(path)
    assert _codes(info.value) == ["E02"]


@pytest.mark.parametrize(
    ("original", "alias"),
    [
        ("", "x1"),
        ("a", ""),
        ("a\nb", "x1"),
        ("a", "x\r1"),
        ("a\0", "x1"),
        ("a", "x/1"),
        ("a", "x\\1"),
    ],
)
def test_bad_characters_are_e03(original: str, alias: str) -> None:
    assert "E03" in [f.code for f in validate_rules(_rules((original, alias)))]


def test_slash_in_original_is_allowed() -> None:
    assert validate_rules(_rules(("db.host/api", "x1"))) == []


def test_duplicate_alias_is_e04() -> None:
    problems = validate_rules(_rules(("a", "X1"), ("b", "X1")))
    assert [f.code for f in problems] == ["E04"]
    assert "«a»" in problems[0].message
    assert "«b»" in problems[0].message


def test_alias_inside_alias_is_e05() -> None:
    problems = validate_rules(_rules(("one", "AAA"), ("two", "AAAB")))
    assert [f.code for f in problems] == ["E05"]


def test_alias_containing_original_ignoring_case_is_e06() -> None:
    problems = validate_rules(_rules(("Pepelac", "zz"), ("b", "xxPEPELACxx")))
    assert [f.code for f in problems] == ["E06"]


def test_all_problems_reported_together(tmp_path: Path) -> None:
    path = tmp_path / "d.toml"
    path.write_text('[rules]\n"a" = "X1"\n"b" = "X1"\n"c" = "q/1"\n', encoding="utf-8")
    with pytest.raises(ObfuscatorError) as info:
        load_dictionary(path)
    assert sorted(_codes(info.value)) == ["E03", "E04"]


def test_case_variants_are_separate_rules() -> None:
    assert validate_rules(_rules(("Pepelac", "Zqv"), ("pepelac", "zqv"), ("PEPELAC", "ZQV"))) == []


def test_resolve_prefers_cli_value() -> None:
    assert resolve_dictionary_path("cli.toml", {ENV_DICTIONARY: "env.toml"}) == Path("cli.toml")


def test_resolve_falls_back_to_environment() -> None:
    assert resolve_dictionary_path(None, {ENV_DICTIONARY: "env.toml"}) == Path("env.toml")


def test_resolve_without_any_value_is_e01() -> None:
    with pytest.raises(ObfuscatorError) as info:
        resolve_dictionary_path(None, {})
    assert _codes(info.value) == ["E01"]


def test_dotted_bare_key_has_hint() -> None:
    with pytest.raises(ObfuscatorError) as info:
        parse_dictionary(b'[rules]\ndb.pepelac.internal = "host-a7.example"\n', "t")
    assert _codes(info.value) == ["E01"]
    assert "в кавычки" in info.value.findings[0].message


def test_words_table_parsed_with_flag() -> None:
    rules = parse_dictionary(b'[rules]\n"Pepelac" = "Zqv"\n[words]\n"sim" = "qx"\n', "t")
    assert rules == (Rule("Pepelac", "Zqv"), Rule("sim", "qx", word=True))


def test_only_words_table_is_enough(tmp_path: Path) -> None:
    path = tmp_path / "d.toml"
    path.write_bytes(b'[words]\n"sim" = "qx"\n')
    assert load_dictionary(path).rules == (Rule("sim", "qx", word=True),)


def test_no_tables_is_e01() -> None:
    with pytest.raises(ObfuscatorError) as info:
        parse_dictionary(b"x = 1\n", "t")
    assert _codes(info.value) == ["E01"]


def test_empty_both_tables_is_e02(tmp_path: Path) -> None:
    path = tmp_path / "d.toml"
    path.write_bytes(b"[rules]\n[words]\n")
    with pytest.raises(ObfuscatorError) as info:
        load_dictionary(path)
    assert _codes(info.value) == ["E02"]


@pytest.mark.parametrize(
    ("original", "alias"),
    [("sim", "Qx"), ("sim", "qX"), ("Sim", "qx"), ("SIM", "Qx"), ("sim", "1x"), ("v2", "qx"), ("вий", "Qx")],
)
def test_word_alias_kind_mismatch_is_e14(original: str, alias: str) -> None:
    assert "E14" in [f.code for f in validate_rules([Rule(original, alias, word=True)])]


@pytest.mark.parametrize(
    ("original", "alias"), [("sim", "qx"), ("Sim", "Qx"), ("SIM", "QX"), ("v2", "q7"), ("вий", "qzx")]
)
def test_word_alias_kind_match_is_valid(original: str, alias: str) -> None:
    assert validate_rules([Rule(original, alias, word=True)]) == []


def test_same_original_in_both_tables_is_e14() -> None:
    problems = validate_rules([Rule("sim", "qx"), Rule("sim", "wk", word=True)])
    assert "E14" in [f.code for f in problems]


def test_short_substring_rule_warns_w04(tmp_path: Path) -> None:
    path = tmp_path / "d.toml"
    path.write_bytes(b'[rules]\n"sim" = "qxz"\n"Pepelac" = "Zqv"\n[words]\n"vi" = "wk"\n')
    warnings = load_dictionary(path).warnings
    assert [(f.code, f.text) for f in warnings] == [("W04", "sim")]
