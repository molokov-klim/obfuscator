"""Словарь замен: чтение TOML (спецификация §3.2) и проверки без проекта (§5.1)."""

import hashlib
import os
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from obfuscator.errors import ObfuscatorError, finding
from obfuscator.models import Finding, Rule
from obfuscator.narrow import as_table

ENV_DICTIONARY = "OBFUSCATOR_DICT"

_FORBIDDEN_IN_BOTH = ("\n", "\r", "\0")
_FORBIDDEN_IN_ALIAS = ("/", "\\")


@dataclass(frozen=True)
class Dictionary:
    """Проверенный словарь.

    Attributes:
        path: Путь к файлу словаря.
        rules: Правила в порядке файла.
        sha256: Хэш байтов файла (для проверки при возврате, E21).
    """

    path: Path
    rules: tuple[Rule, ...]
    sha256: str


def resolve_dictionary_path(cli_value: str | None, environ: Mapping[str, str] | None = None) -> Path:
    """Находит путь к словарю: ``--dict``, иначе ``OBFUSCATOR_DICT``.

    Args:
        cli_value: Значение ``--dict`` или ``None``.
        environ: Окружение; ``None`` — ``os.environ``.

    Returns:
        Путь к словарю.

    Raises:
        ObfuscatorError: E01, если путь не задан.
    """
    env = os.environ if environ is None else environ
    value = cli_value or env.get(ENV_DICTIONARY)
    if not value:
        raise ObfuscatorError.single("E01", f"укажите --dict или переменную окружения {ENV_DICTIONARY}")
    return Path(value)


def load_dictionary(path: Path) -> Dictionary:
    """Читает и проверяет словарь.

    Args:
        path: Путь к файлу словаря.

    Returns:
        Проверенный словарь.

    Raises:
        ObfuscatorError: E01 — файл не читается или схема неверна; E02–E06 — проверки §5.1 (все найденные сразу).
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ObfuscatorError.single("E01", f"не удалось прочитать {path}: {exc.strerror or exc}") from exc
    rules = parse_dictionary(data, str(path))
    problems = validate_rules(rules)
    if problems:
        raise ObfuscatorError(problems)
    return Dictionary(path=path, rules=rules, sha256=hashlib.sha256(data).hexdigest())


def parse_dictionary(data: bytes, source: str) -> tuple[Rule, ...]:
    """Разбирает TOML словаря по схеме §3.2.

    Args:
        data: Байты файла.
        source: Имя источника для сообщений.

    Returns:
        Правила в порядке файла.

    Raises:
        ObfuscatorError: E01 — не UTF-8, не TOML или неверная схема.
    """
    try:
        document = tomllib.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ObfuscatorError.single("E01", f"{source}: файл не в UTF-8") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ObfuscatorError.single("E01", f"{source}: не TOML: {exc}") from exc

    extra = sorted(key for key in document if key != "rules")
    if extra:
        raise ObfuscatorError.single("E01", f"{source}: неизвестные ключи верхнего уровня: {', '.join(extra)}")
    table = as_table(document.get("rules"))
    if table is None:
        raise ObfuscatorError.single("E01", f"{source}: нет таблицы [rules]")

    rules: list[Rule] = []
    for original, alias in table.items():
        if as_table(alias) is not None:
            raise ObfuscatorError.single(
                "E01",
                f"{source}: ключ «{original}» прочитан как таблица — в TOML точка в ключе без кавычек означает "
                f'вложенность; оригинал с точкой возьмите в кавычки: "{original}.…" = "…"',
                text=original,
            )
        if not isinstance(alias, str):
            raise ObfuscatorError.single("E01", f"{source}: алиас для «{original}» должен быть строкой", text=original)
        rules.append(Rule(original=original, alias=alias))
    return tuple(rules)


def validate_rules(rules: Sequence[Rule]) -> list[Finding]:
    """Проверяет правила без проекта (§5.1 п. 2–6).

    Args:
        rules: Правила.

    Returns:
        Все найденные ошибки E02–E06; пусто, если словарь корректен.
    """
    if not rules:
        return [finding("E02")]

    problems: list[Finding] = []
    for rule in rules:
        problems.extend(_check_characters(rule))

    by_alias: dict[str, list[str]] = {}
    for rule in rules:
        by_alias.setdefault(rule.alias, []).append(rule.original)
    for alias, originals in by_alias.items():
        if len(originals) > 1:
            listed = ", ".join(f"«{o}»" for o in originals)
            problems.append(finding("E04", f"«{alias}» ← {listed}", text=alias))

    aliases = sorted(by_alias)
    for inner in aliases:
        for outer in aliases:
            if inner and inner != outer and inner in outer:
                problems.append(finding("E05", f"«{inner}» входит в «{outer}»", text=inner))

    folded_originals = [(rule.original, rule.original.casefold()) for rule in rules if rule.original]
    for alias in aliases:
        folded_alias = alias.casefold()
        for original, folded_original in folded_originals:
            if folded_original in folded_alias:
                problems.append(finding("E06", f"алиас «{alias}» содержит оригинал «{original}»", text=alias))
    return problems


def _check_characters(rule: Rule) -> list[Finding]:
    """Проверяет символы правила (§5.1 п. 3).

    Args:
        rule: Правило.

    Returns:
        Ошибки E03.
    """
    problems: list[Finding] = []
    if not rule.original:
        problems.append(finding("E03", f"пустой оригинал для алиаса «{rule.alias}»", text=rule.alias))
    if not rule.alias:
        problems.append(finding("E03", f"пустой алиас для «{rule.original}»", text=rule.original))
    for name, value in (("оригинал", rule.original), ("алиас", rule.alias)):
        bad = [repr(ch) for ch in _FORBIDDEN_IN_BOTH if ch in value]
        if bad:
            problems.append(finding("E03", f"{name} {value!r} содержит {', '.join(bad)}", text=value))
    bad_alias = [ch for ch in _FORBIDDEN_IN_ALIAS if ch in rule.alias]
    if bad_alias:
        problems.append(finding("E03", f"алиас «{rule.alias}» содержит {' '.join(bad_alias)}", text=rule.alias))
    return problems
