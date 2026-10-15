"""Построчное восстановление изменённого текстового файла (спецификация §5.7 п. 9–10)."""

import difflib
from collections import Counter
from dataclasses import dataclass

from obfuscator.replacer import Replacer


@dataclass(frozen=True)
class MergeResult:
    """Результат восстановления.

    Attributes:
        text: Новая версия файла оригинала.
        restored: Число обратных замен по алиасам.
        new_lines: Новые строки агента (до обратной замены) с номерами строк с 1 в новой версии.
    """

    text: str
    restored: Counter[str]
    new_lines: tuple[tuple[int, str], ...]


def split_lines(text: str) -> list[str]:
    r"""Делит текст на строки только по ``\n``, сохраняя разделитель; ``\r`` и прочие символы остаются в строке.

    Args:
        text: Текст.

    Returns:
        Строки; пустой текст — пустой список; последняя строка может не иметь ``\n``.
    """
    lines: list[str] = []
    start = 0
    while True:
        end = text.find("\n", start)
        if end == -1:
            if start < len(text):
                lines.append(text[start:])
            return lines
        lines.append(text[start : end + 1])
        start = end + 1


def merge_text(original: str, baseline: str, current: str, backward: Replacer) -> MergeResult:
    """Переносит изменения копии в оригинал построчно.

    Участки, где копия не менялась относительно снимка, берутся из оригинала байт в байт; заменённые и вставленные
    строки копии проходят обратную замену; удалённые строки исчезают.

    Args:
        original: Текст оригинала на точке отсчёта.
        baseline: Текст копии на точке отсчёта (прямая замена ``original``).
        current: Текущий текст копии.
        backward: Заменитель «алиас → оригинал».

    Returns:
        Новая версия оригинала, счётчик восстановленных замен и новые строки.

    Raises:
        ValueError: Число строк оригинала и снимка не совпадает (нарушен инвариант §5.1 п. 3).
    """
    original_lines = split_lines(original)
    baseline_lines = split_lines(baseline)
    current_lines = split_lines(current)
    if len(original_lines) != len(baseline_lines):
        raise ValueError("число строк оригинала и снимка копии различается")

    result: list[str] = []
    restored: Counter[str] = Counter()
    new_lines: list[tuple[int, str]] = []
    matcher = difflib.SequenceMatcher(None, baseline_lines, current_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            result.extend(original_lines[i1:i2])
        elif tag in ("replace", "insert"):
            for index in range(j1, j2):
                line = current_lines[index]
                new_lines.append((len(result) + 1, line))
                text, counts = backward.replace(line)
                restored.update(counts)
                result.append(text)
    return MergeResult(text="".join(result), restored=restored, new_lines=tuple(new_lines))


def restore_new_text(current: str, backward: Replacer) -> MergeResult:
    """Восстанавливает новый файл агента целиком.

    Args:
        current: Текст файла в копии.
        backward: Заменитель «алиас → оригинал».

    Returns:
        Текст для оригинала, счётчик замен, все строки как новые.
    """
    lines = split_lines(current)
    text, restored = backward.replace(current)
    return MergeResult(text=text, restored=restored, new_lines=tuple((i + 1, line) for i, line in enumerate(lines)))
