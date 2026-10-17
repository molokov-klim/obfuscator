"""Свойства на случайных данных (hypothesis): обратимость замены и сохранность нетронутых строк."""

from hypothesis import given, settings
from hypothesis import strategies as st

from obfuscator.dictionary import validate_rules
from obfuscator.merge import merge_text, split_lines
from obfuscator.models import Rule
from obfuscator.replacer import backward, forward

# Оригиналы и текст — из одного алфавита, алиасы — из непересекающегося: так алиасы не возникают в тексте сами,
# а проверка E05 гарантирует однозначность обратной замены на стыках алиасов.
TEXT_ALPHABET = "abc \n\r"
ALIAS_ALPHABET = "XYZ"

originals = st.text(alphabet="abc", min_size=1, max_size=4)
aliases = st.text(alphabet=ALIAS_ALPHABET, min_size=2, max_size=5)


@st.composite
def valid_rules(draw: st.DrawFn) -> list[Rule]:
    pairs = draw(st.dictionaries(originals, aliases, min_size=1, max_size=6))
    rules = [Rule(original=o, alias=a) for o, a in pairs.items()]
    if validate_rules(rules):
        rules = rules[:1]
    return rules


@given(rules=valid_rules(), text=st.text(alphabet=TEXT_ALPHABET, max_size=200))
@settings(max_examples=300)
def test_backward_inverts_forward(rules: list[Rule], text: str) -> None:
    assert backward(rules).apply(forward(rules).apply(text)) == text


@given(rules=valid_rules(), text=st.text(alphabet=TEXT_ALPHABET, max_size=200))
@settings(max_examples=200)
def test_forward_keeps_line_count(rules: list[Rule], text: str) -> None:
    assert len(split_lines(forward(rules).apply(text))) == len(split_lines(text))


@given(
    rules=valid_rules(),
    text=st.text(alphabet=TEXT_ALPHABET, max_size=200),
    edits=st.lists(st.tuples(st.integers(min_value=0, max_value=50), st.text(alphabet="abcXYZ ", max_size=10))),
)
@settings(max_examples=200)
def test_untouched_lines_are_preserved(rules: list[Rule], text: str, edits: list[tuple[int, str]]) -> None:
    fwd = forward(rules)
    baseline = fwd.apply(text)
    lines = split_lines(baseline)
    original_lines = split_lines(text)
    touched: set[int] = set()
    for index, new in edits:
        if index < len(lines):
            lines[index] = new + "\n"
            touched.add(index)
    result = merge_text(text, baseline, "".join(lines), backward(rules))
    result_lines = split_lines(result.text)
    assert len(result_lines) == len(original_lines)
    for index, line in enumerate(original_lines):
        if index not in touched:
            assert result_lines[index] == line
