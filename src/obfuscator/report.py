"""Текст отчёта (спецификация §6.1)."""

from obfuscator.models import Finding, Report


def finding_line(item: Finding) -> str:
    """Строка находки: ``<код> <путь>[:<строка>] <сообщение>``.

    Args:
        item: Находка.

    Returns:
        Строка без перевода строки.
    """
    where = item.path or ""
    if item.path is not None and item.line is not None:
        where += f":{item.line}"
    return f"{item.code} {where} {item.message}" if where else f"{item.code} {item.message}"


SAMPLE_PLACES = 3
_LEAK_HINT = "  → добавьте каждое написание в словарь отдельным правилом или в .obfallow.toml"


def _plural(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "находка"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "находки"
    return "находок"


def _place(item: Finding) -> str:
    place = item.path or ""
    return f"{place}:{item.line}" if item.line is not None else place


def summary_lines(items: list[Finding], *, verbose: bool = False) -> list[str]:
    """Строки находок: без ``verbose`` одинаковые находки (код + написание) сворачиваются в одну строку.

    Свёрнутая строка: ``<код> «<написание>» — <N> находок: <первые места>, …``. Порядок групп — по первому
    появлению; находки без написания не сворачиваются.

    Args:
        items: Находки.
        verbose: Не сворачивать.

    Returns:
        Строки без отступа и перевода строки.
    """
    if verbose:
        return [finding_line(item) for item in items]
    groups: dict[tuple[str, str], list[Finding]] = {}
    order: list[tuple[str, str] | Finding] = []
    for item in items:
        if item.text is None:
            order.append(item)
            continue
        key = (item.code, item.text)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)
    lines: list[str] = []
    for entry in order:
        if isinstance(entry, Finding):
            lines.append(finding_line(entry))
            continue
        group = groups[entry]
        if len(group) == 1:
            lines.append(finding_line(group[0]))
            continue
        code, text = entry
        places = ", ".join(_place(item) for item in group[:SAMPLE_PLACES])
        more = ", …" if len(group) > SAMPLE_PLACES else ""
        lines.append(f"{code} «{text}» — {len(group)} {_plural(len(group))}: {places}{more}")
    return lines


def _findings_block(title: str, items: list[Finding], *, verbose: bool = False) -> list[str]:
    lines = [f"{title}: {len(items)}"]
    lines.extend(f"  {line}" for line in summary_lines(items, verbose=verbose))
    if not verbose and any(item.code == "E12" for item in items):
        lines.append(_LEAK_HINT)
    if not verbose and len(summary_lines(items)) < len(items):
        lines.append("  (одинаковые находки свёрнуты; полный список — с --verbose)")
    return lines


def format_refusal(
    command: str, errors: list[Finding], warnings: list[Finding] | None = None, *, verbose: bool = False
) -> str:
    """Отчёт об отказе.

    Args:
        command: Заголовок команды, например ``obfuscator obfuscate``.
        errors: Ошибки.
        warnings: Предупреждения, если успели появиться.
        verbose: Полный список находок без свёртки.

    Returns:
        Текст отчёта.
    """
    lines = [f"{command} — ОТКАЗ"]
    lines.extend(_findings_block("Ошибки", errors, verbose=verbose))
    if warnings:
        lines.extend(_findings_block("Предупреждения", warnings, verbose=verbose))
    lines.append("Ничего не изменено.")
    return "\n".join(lines) + "\n"


def format_obfuscate(report: Report, aliases: dict[str, str], *, verbose: bool = False) -> str:
    """Отчёт об успешной обфускации.

    Args:
        report: Отчёт сценария.
        aliases: Оригинал → алиас для строк сводки по правилам.
        verbose: Добавить подробности по файлам.

    Returns:
        Текст отчёта.
    """
    c = report.counters
    origin = "git" if c.get("git") else "не git"
    lines = [
        "obfuscator obfuscate — OK",
        f"Вход: путей {c.get('inputs', 0)}, корень {report.locations.get('root', '')} ({origin})",
        (
            f"Файлы: скопировано {c.get('copied', 0)} (текстовых {c.get('text', 0)}, бинарных {c.get('binary', 0)}); "
            f"исключено {c.get('excluded_ignore', 0) + c.get('excluded_service', 0)} "
            f"(.obfignore {c.get('excluded_ignore', 0)}, служебные {c.get('excluded_service', 0)}); "
            f"пропущено {c.get('skipped', 0)}"
        ),
        (
            f"Замены: {c.get('replacements', 0)} в {c.get('files_with_replacements', 0)} файлах; "
            f"путей изменено {c.get('paths_changed', 0)}"
        ),
    ]
    labels = {original: f"{original} → {aliases.get(original, '?')}" for original in report.per_rule}
    width = max((len(label) for label in labels.values()), default=0)
    for original, count in report.per_rule.items():
        lines.append(f"  {labels[original].ljust(width)}  {count}")
    if verbose:
        lines.append("По файлам:")
        lines.extend(f"  {path}  {count}" for path, count in report.per_file.items())
        for category, paths in report.files.items():
            lines.append(f"{category.capitalize()}: {len(paths)}")
            lines.extend(f"  {path}" for path in paths)
    lines.extend(_findings_block("Предупреждения", report.warnings, verbose=verbose))
    lines.append("Ошибки: 0")
    lines.append(f"Копия: {report.locations.get('copy', '')}")
    lines.append(f"Состояние: {report.locations.get('state', '')}")
    return "\n".join(lines) + "\n"


def format_restore(report: Report, mode: str, *, verbose: bool = False) -> str:
    """Отчёт об успешном возврате.

    Args:
        report: Отчёт сценария.
        mode: ``worktree`` или ``patch``.
        verbose: Добавить списки файлов.

    Returns:
        Текст отчёта.
    """
    c = report.counters
    flag = "--worktree" if mode == "worktree" else "--patch"
    lines = [
        f"obfuscator restore {flag} — OK",
        (
            f"Изменения: изменено {c.get('modified', 0)}, добавлено {c.get('added', 0)}, "
            f"удалено {c.get('deleted', 0)}, переименовано {c.get('renamed', 0)}; "
            f"не перенесено {c.get('not_transferred', 0)}"
        ),
        f"Восстановлено замен: {c.get('restored', 0)}",
    ]
    if verbose:
        for category, paths in report.files.items():
            lines.append(f"{category.capitalize()}: {len(paths)}")
            lines.extend(f"  {path}" for path in paths)
    lines.extend(_findings_block("Предупреждения", report.warnings, verbose=verbose))
    lines.append("Ошибки: 0")
    root = report.locations.get("root", "")
    changed = sum(c.get(key, 0) for key in ("modified", "added", "deleted", "renamed"))
    if changed == 0:
        lines.append("Изменений для переноса нет; оригинал и состояние не изменены.")
    elif mode == "worktree":
        lines.append(f"Следующий шаг: git -C {root} diff; затем закоммитьте изменения")
    else:
        patch = report.locations.get("patch", "")
        lines.append(f"Патч: {patch}; применить: cd {root} && git apply {patch}")
    return "\n".join(lines) + "\n"
