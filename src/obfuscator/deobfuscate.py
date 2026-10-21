"""Сценарий деобфускации: обратная замена любых файлов без состояния (спецификация §5.8, rev3)."""

from collections import Counter
from pathlib import Path

from obfuscator.allow import AllowList
from obfuscator.dictionary import Dictionary
from obfuscator.errors import ObfuscatorError, finding
from obfuscator.fsio import make_staging, remove_tree, swap_into_place, write_tree
from obfuscator.inputs import resolve_plain_inputs
from obfuscator.models import Finding, Report
from obfuscator.obfuscate import check_out_fresh, check_out_overlap, read_sources
from obfuscator.paths import PathPair, check_copy_paths, transform_path
from obfuscator.replacer import backward
from obfuscator.scanner import Scanner, case_mismatch_findings, leak_findings, path_leak_findings

_RESULT = "каталог результата"


def _path_case_findings(alias_scanner: Scanner, aliases: frozenset[str], path: str) -> list[Finding]:
    return [
        finding("W11", f"в пути: «{m.text}»", path=path, text=m.text)
        for m in alias_scanner.find(path)
        if m.text not in aliases
    ]


def run_deobfuscate(paths: list[Path], out: Path, dictionary: Dictionary) -> Report:
    """Заменяет алиасы оригиналами в файлах входа и пишет результат в новый каталог.

    Args:
        paths: Файлы и каталоги входа.
        out: Каталог результата: не существует или пуст.
        dictionary: Проверенный словарь.

    Returns:
        Отчёт об успешной деобфускации.

    Raises:
        ObfuscatorError: Отказ §5.8 (E07, E08, E10); на диске при этом ничего не меняется.
    """
    out = out.resolve()
    inputs = resolve_plain_inputs(paths, protected=[dictionary.path, out])
    check_out_overlap(out, inputs, _RESULT)
    check_out_fresh(out, _RESULT)
    sources = read_sources(inputs)
    rules = dictionary.rules
    bwd = backward(rules)
    originals = Scanner.originals(rules)
    alias_scanner = Scanner.aliases(rules, ignore_case=True)
    exact_aliases = frozenset(rule.alias for rule in rules)
    nothing_allowed = AllowList()

    per_rule: Counter[str] = Counter()
    per_file: dict[str, int] = {}
    result: dict[str, bytes] = {}
    pairs: list[PathPair] = []
    warnings: list[Finding] = [*inputs.skipped]

    for source in sources:
        target = transform_path(source.path, bwd)
        pairs.append(PathPair(original=source.path, copy=target))
        warnings.extend(path_leak_findings(originals, source.path, source.path, nothing_allowed, "W10"))
        warnings.extend(_path_case_findings(alias_scanner, exact_aliases, source.path))
        if source.text is None:
            data = source.data
            found = alias_scanner.find_bytes(data)
            if found:
                text = found[0].decode("utf-8", errors="replace")
                warnings.append(finding("W15", f"«{text}»", path=source.path, text=text))
        else:
            warnings.extend(leak_findings(originals, source.text, source.path, nothing_allowed, "W10"))
            warnings.extend(case_mismatch_findings(alias_scanner, exact_aliases, source.text, source.path))
            restored, counts = bwd.replace(source.text)
            per_rule.update(counts)
            if counts:
                per_file[source.path] = sum(counts.values())
            data = restored.encode("utf-8")
        result[target] = data

    errors, path_warnings = check_copy_paths(pairs)
    if errors:
        raise ObfuscatorError(errors)
    warnings.extend(path_warnings)

    staged = make_staging(out)
    try:
        write_tree(staged, result)
        swap_into_place([(staged, out)])
    finally:
        remove_tree(staged)

    report = Report(command="deobfuscate", warnings=warnings)
    report.per_rule = {rule.alias: per_rule[rule.alias] for rule in rules if per_rule[rule.alias]}
    report.per_file = dict(sorted(per_file.items()))
    report.counters = {
        "inputs": len(inputs.inputs),
        "processed": len(sources),
        "text": sum(1 for s in sources if s.text is not None),
        "binary": sum(1 for s in sources if s.text is None),
        "skipped": len(inputs.skipped) + len(inputs.excluded_service),
        "replacements": sum(per_file.values()),
        "files_with_replacements": len(per_file),
        "paths_changed": sum(1 for pair in pairs if pair.copy != pair.original),
    }
    report.files = {
        "обработаны": [s.path for s in sources],
        "бинарные": [s.path for s in sources if s.text is None],
        "пропущены": [*inputs.excluded_service, *(item.path or "" for item in inputs.skipped)],
    }
    report.locations = {"root": str(inputs.root), "out": str(out)}
    return report
