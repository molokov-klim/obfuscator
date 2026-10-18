"""Словарь замен: чтение TOML (спецификация §3.2) и проверки без проекта (§5.1)."""

import hashlib
import os
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from obfuscator.errors import ObfuscatorError, finding
from obfuscator.matcher import char_kind
from obfuscator.models import Finding, Rule
from obfuscator.narrow import as_table

ENV_DICTIONARY = "OBFUSCATOR_DICT"
TABLES = ("rules", "words")
SHORT_ORIGINAL = 4

_FORBIDDEN_IN_BOTH = ("\n", "\r", "\0")
_FORBIDDEN_IN_ALIAS = ("/", "\\")


@dataclass(frozen=True)
class Dictionary:
    """Проверенный словарь.

    Attributes:
        path: Путь к файлу словаря.
        rules: Правила в порядке файла.
        sha256: Хэш байтов файла (для проверки при возврате, E21).
        warnings: Предупреждения о словаре (W04).
    """

    path: Path
    rules: tuple[Rule, ...]
    sha256: str
    warnings: tuple[Finding, ...] = ()


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
    return Dictionary(
        path=path, rules=rules, sha256=hashlib.sha256(data).hexdigest(), warnings=tuple(dictionary_warnings(rules))
    )


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

    extra = sorted(key for key in document if key not in TABLES)
    if extra:
        raise ObfuscatorError.single("E01", f"{source}: неизвестные ключи верхнего уровня: {', '.join(extra)}")
    if not any(name in document for name in TABLES):
        raise ObfuscatorError.single("E01", f"{source}: нет таблицы [rules] или [words]")

    rules: list[Rule] = []
    for name in TABLES:
        if name not in document:
            continue
        table = as_table(document[name])
        if table is None:
            raise ObfuscatorError.single("E01", f"{source}: [{name}] должна быть таблицей")
        rules.extend(_parse_table(table, source, word=name == "words"))
    return tuple(rules)


def _parse_table(table: dict[str, object], source: str, *, word: bool) -> list[Rule]:
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
        rules.append(Rule(original=original, alias=alias, word=word))
    return rules


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

    problems.extend(_check_words(rules))

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


def _check_words(rules: Sequence[Rule]) -> list[Finding]:
    """Проверки правил по словам (§5.1 п. 7, FR-074).

    Args:
        rules: Правила.

    Returns:
        Ошибки E14.
    """
    problems: list[Finding] = []
    kinds = {False: "rules", True: "words"}
    seen: dict[str, bool] = {}
    for rule in rules:
        if rule.original in seen and seen[rule.original] != rule.word:
            problems.append(
                finding("E14", f"«{rule.original}» задан и в [{kinds[False]}], и в [{kinds[True]}]", text=rule.original)
            )
        seen[rule.original] = rule.word
        if not rule.word or not rule.original or not rule.alias:
            continue
        for side, index in (("первый", 0), ("последний", -1)):
            original_kind, alias_kind = char_kind(rule.original[index]), char_kind(rule.alias[index])
            if original_kind != alias_kind:
                problems.append(
                    finding(
                        "E14",
                        f"«{rule.original}» → «{rule.alias}»: {side} символ алиаса — {_KIND_NAMES[alias_kind]}, "
                        f"а у оригинала — {_KIND_NAMES[original_kind]}",
                        text=rule.alias,
                    )
                )
    return problems


_KIND_NAMES = {
    "lower": "строчная буква",
    "upper": "заглавная буква",
    "letter": "буква без регистра",
    "other": "не буква",
}


def dictionary_warnings(rules: Sequence[Rule]) -> list[Finding]:
    """Предупреждения о словаре: правило подстроки с коротким оригиналом (W04, FR-075).

    Args:
        rules: Правила.

    Returns:
        Предупреждения W04.
    """
    return [
        finding("W04", f"«{rule.original}»: перенесите в [words], чтобы не задевать другие слова", text=rule.original)
        for rule in rules
        if not rule.word and 0 < len(rule.original) < SHORT_ORIGINAL
    ]
