import pytest

from obfuscator.merge import merge_text, restore_new_text, split_lines
from obfuscator.models import Rule
from obfuscator.replacer import backward, forward

RULES = [Rule("Pepelac", "Zqv"), Rule("pepelac", "zqv")]
FWD = forward(RULES)
BWD = backward(RULES)


def test_split_only_on_lf() -> None:
    assert split_lines("a\r\nb\x0bc d\nlast") == ["a\r\n", "b\x0bc d\n", "last"]
    assert split_lines("") == []
    assert split_lines("x\n") == ["x\n"]


def test_unchanged_copy_returns_original_bytes() -> None:
    original = "import Pepelac\r\nx = 1\n"
    assert merge_text(original, FWD.apply(original), FWD.apply(original), BWD).text == original


def test_untouched_lines_come_from_original() -> None:
    original = "a = Pepelac\nb = 2\nc = 3\n"
    baseline = FWD.apply(original)
    current = baseline.replace("b = 2", "b = Zqv + zqv")
    result = merge_text(original, baseline, current, BWD)
    assert result.text == "a = Pepelac\nb = Pepelac + pepelac\nc = 3\n"
    assert result.restored == {"Zqv": 1, "zqv": 1}
    assert result.new_lines == ((2, "b = Zqv + zqv\n"),)


def test_untouched_line_is_taken_from_original_not_reversed() -> None:
    # Обратная замена этой строки неоднозначна на стыке алиаса и текста: «aq» → «abz» → «wz».
    # Нетронутая строка обязана прийти из оригинала, а не из обратной замены копии.
    rules = [Rule("q", "bz"), Rule("w", "ab")]
    fwd, bwd = forward(rules), backward(rules)
    original = "aq\nedit me\n"
    baseline = fwd.apply(original)
    assert bwd.apply(baseline) != original
    current = baseline.replace("edit me", "edited")
    assert merge_text(original, baseline, current, bwd).text == "aq\nedited\n"


def test_insert_and_delete() -> None:
    original = "l1\nl2 Pepelac\nl3\n"
    baseline = FWD.apply(original)
    current = "l0 zqv\nl1\nl3\n"
    result = merge_text(original, baseline, current, BWD)
    assert result.text == "l0 pepelac\nl1\nl3\n"
    assert [n for n, _ in result.new_lines] == [1]


def test_missing_final_newline_and_crlf_preserved() -> None:
    original = "a\r\nb Pepelac"
    baseline = FWD.apply(original)
    current = "a\r\nb Zqv\r\nc"
    assert merge_text(original, baseline, current, BWD).text == "a\r\nb Pepelac\r\nc"


def test_line_count_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="число строк"):
        merge_text("a\nb\n", "a\n", "a\n", BWD)


def test_new_file_is_fully_restored() -> None:
    result = restore_new_text("x = Zqv\ny = 1\n", BWD)
    assert result.text == "x = Pepelac\ny = 1\n"
    assert [n for n, _ in result.new_lines] == [1, 2]
