"""Обфускация путей и их допустимость на Linux и Windows (спецификация §5.4)."""

from collections.abc import Sequence
from dataclasses import dataclass

from obfuscator.errors import finding
from obfuscator.models import Finding
from obfuscator.replacer import Replacer

_FORBIDDEN_CHARS = frozenset('<>:"|?*') | frozenset(chr(code) for code in range(32))
_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"] + [f"COM{i}" for i in range(1, 10)] + [f"LPT{i}" for i in range(1, 10)]
)
MAX_COMPONENT_LENGTH = 255


@dataclass(frozen=True)
class PathPair:
    """Путь оригинала и соответствующий путь копии (относительные, разделитель ``/``).

    Attributes:
        original: Путь оригинала.
        copy: Путь копии.
    """

    original: str
    copy: str


def transform_path(path: str, replacer: Replacer) -> str:
    """Применяет замену к каждой части пути отдельно.

    Args:
        path: Относительный путь с разделителем ``/``.
        replacer: Заменитель.

    Returns:
        Путь с заменёнными частями.
    """
    return "/".join(replacer.apply(part) for part in path.split("/"))


def component_problem(component: str) -> str | None:
    """Проверяет часть пути на допустимость в Windows и Linux.

    Args:
        component: Имя каталога или файла.

    Returns:
        Причина недопустимости или ``None``.
    """
    bad = sorted({ch for ch in component if ch in _FORBIDDEN_CHARS})
    if bad:
        return "запрещённые символы " + " ".join(repr(ch) for ch in bad)
    if component.split(".", 1)[0].strip().upper() in _RESERVED_NAMES:
        return "зарезервированное имя Windows"
    if component.endswith((".", " ")):
        return "оканчивается точкой или пробелом"
    if len(component) > MAX_COMPONENT_LENGTH:
        return f"длиннее {MAX_COMPONENT_LENGTH} символов"
    return None


def check_copy_paths(pairs: Sequence[PathPair]) -> tuple[list[Finding], list[Finding]]:
    """Проверяет пути копии (FR-014).

    Недопустимость или конфликт регистра, созданные заменой, — E10; уже имевшиеся в оригинале — W02.

    Args:
        pairs: Пары путей оригинала и копии; число частей в паре совпадает.

    Returns:
        Ошибки E10 и предупреждения W02.
    """
    errors: list[Finding] = []
    warnings: list[Finding] = []
    for pair in pairs:
        for original_part, copy_part in zip(pair.original.split("/"), pair.copy.split("/"), strict=True):
            problem = component_problem(copy_part)
            if problem is None:
                continue
            if component_problem(original_part) is not None:
                warnings.append(finding("W02", f"«{original_part}»: {problem}", path=pair.original))
            else:
                errors.append(finding("E10", f"часть пути после замены: {problem}", path=pair.original))
            break

    by_folded: dict[str, list[PathPair]] = {}
    for pair in pairs:
        by_folded.setdefault(pair.copy.casefold(), []).append(pair)
    for group in by_folded.values():
        if len(group) < 2:
            continue
        originals = sorted(pair.original for pair in group)
        listed = ", ".join(originals)
        if len({original.casefold() for original in originals}) == 1:
            warnings.append(finding("W02", f"пути различаются только регистром: {listed}", path=originals[0]))
        else:
            errors.append(
                finding("E10", f"после замены пути различаются только регистром: {listed}", path=originals[0])
            )
    return errors, warnings
