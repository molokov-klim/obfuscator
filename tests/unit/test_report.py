from obfuscator.errors import finding
from obfuscator.models import Finding
from obfuscator.report import format_refusal, summary_lines


def _leaks(text: str, count: int) -> list[Finding]:
    return [finding("E12", f"«{text}»", path=f"src/f{i}.py", line=i + 1, text=text) for i in range(count)]


def test_same_spelling_is_collapsed_with_sample_places() -> None:
    lines = summary_lines(_leaks("Shadowstep", 5) + _leaks("APPIUM", 2) + _leaks("solo", 1))
    assert lines == [
        "E12 «Shadowstep» — 5 находок: src/f0.py:1, src/f1.py:2, src/f2.py:3, …",
        "E12 «APPIUM» — 2 находки: src/f0.py:1, src/f1.py:2",
        "E12 src/f0.py:1 утечка оригинала в копию: «solo»",
    ]


def test_findings_without_text_are_not_collapsed() -> None:
    items = [finding("E22", "файл изменён", path="a.py"), finding("E22", "файл изменён", path="b.py")]
    assert summary_lines(items) == [
        "E22 a.py оригинал изменился после точки отсчёта: файл изменён",
        "E22 b.py оригинал изменился после точки отсчёта: файл изменён",
    ]


def test_verbose_lists_everything() -> None:
    assert len(summary_lines(_leaks("x", 50), verbose=True)) == 50


def test_plural_forms() -> None:
    assert "21 находка" in summary_lines(_leaks("a", 21))[0]
    assert "22 находки" in summary_lines(_leaks("a", 22))[0]
    assert "11 находок" in summary_lines(_leaks("a", 11))[0]


def test_refusal_report_has_total_hint_and_note() -> None:
    text = format_refusal("obfuscator obfuscate", _leaks("Shadowstep", 6618))
    assert "Ошибки: 6618" in text
    assert "E12 «Shadowstep» — 6618 находок" in text
    assert "добавьте каждое написание в словарь" in text
    assert "полный список — с --verbose" in text
    assert len(text.splitlines()) < 10
