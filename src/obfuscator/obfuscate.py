"""Сценарий обфускации (спецификация §5.6)."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from obfuscator import __version__
from obfuscator.allow import load_allow
from obfuscator.dictionary import Dictionary
from obfuscator.errors import ObfuscatorError, finding
from obfuscator.fsio import hash_tree, is_empty_dir, make_staging, remove_tree, swap_into_place, write_tree
from obfuscator.gitio import Git
from obfuscator.inputs import InputSet, resolve_inputs
from obfuscator.models import FileEntry, FileKind, Finding, Report
from obfuscator.paths import PathPair, check_copy_paths, transform_path
from obfuscator.replacer import backward, forward
from obfuscator.scanner import Scanner, binary_findings, leak_findings, path_leak_findings
from obfuscator.state import BASELINE_DIR, State, now_iso, read_state, sha256_hex, state_dir_for, write_state


@dataclass(frozen=True)
class SourceFile:
    """Файл входа, прочитанный с диска.

    Attributes:
        path: Путь оригинала относительно корня.
        data: Байты.
        text: Текст, если файл декодируется как UTF-8, иначе ``None``.
    """

    path: str
    data: bytes
    text: str | None

    @property
    def kind(self) -> FileKind:
        """``text`` или ``binary``."""
        return "binary" if self.text is None else "text"


def read_sources(inputs: InputSet) -> list[SourceFile]:
    """Читает отобранные файлы и определяет их тип (§5.2 п. 9).

    Args:
        inputs: Разобранный вход.

    Returns:
        Файлы в порядке путей.
    """
    sources: list[SourceFile] = []
    for relative in inputs.files:
        data = (inputs.root / relative).read_bytes()
        try:
            text: str | None = data.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        sources.append(SourceFile(path=relative, data=data, text=text))
    return sources


def _check_out(out: Path, inputs: InputSet) -> None:
    """Проверяет каталог копии (FR-018, §5.6 п. 8).

    Args:
        out: Абсолютный путь копии.
        inputs: Разобранный вход.

    Raises:
        ObfuscatorError: E08.
    """
    for relative in inputs.inputs:
        item = (inputs.root / relative).resolve()
        if out == item or item in out.parents:
            raise ObfuscatorError.single("E08", f"каталог копии внутри входа: {out}")
        if out in item.parents:
            raise ObfuscatorError.single("E08", f"вход внутри каталога копии: {out}")
    state_dir = state_dir_for(out)
    if not out.exists():
        if state_dir.exists():
            raise ObfuscatorError.single("E08", f"каталог состояния уже существует без копии: {state_dir}")
        return
    if not out.is_dir():
        raise ObfuscatorError.single("E08", f"--out — не каталог: {out}")
    if is_empty_dir(out) and not state_dir.exists():
        return
    if not state_dir.exists():
        raise ObfuscatorError.single("E08", f"каталог копии не пуст: {out}")
    state = read_state(state_dir)
    if Path(state.root) != inputs.root or tuple(state.inputs) != inputs.inputs:
        raise ObfuscatorError.single("E08", f"{out} — копия другого входа ({state.root})")
    expected = {entry.copy_path: entry.copy_sha256 for entry in state.files}
    if hash_tree(out) != expected:
        raise ObfuscatorError.single(
            "E08", f"в копии {out} есть невозвращённые изменения: выполните restore или удалите копию и состояние"
        )


def run_obfuscate(paths: list[Path], out: Path, dictionary: Dictionary, git: Git) -> Report:
    """Строит обфусцированную копию и состояние.

    Args:
        paths: Пути входа.
        out: Каталог копии.
        dictionary: Проверенный словарь.
        git: Порт git.

    Returns:
        Отчёт об успешной обфускации.

    Raises:
        ObfuscatorError: Любой отказ §5.6; на диске при этом ничего не меняется.
    """
    out = out.resolve()
    state_dir = state_dir_for(out)
    inputs = resolve_inputs(paths, git, protected=[dictionary.path, out, state_dir])
    _check_out(out, inputs)
    allow = load_allow(inputs.root)
    sources = read_sources(inputs)
    rules = dictionary.rules
    fwd, bwd = forward(rules), backward(rules)

    # §5.6 п. 3: алиасы не должны встречаться в проекте.
    alias_scanner = Scanner((rule.alias for rule in rules), ignore_case=False)
    alias_hits: list[Finding] = []
    for source in sources:
        for match in alias_scanner.find(source.path):
            alias_hits.append(finding("E09", f"в пути: «{match.text}»", path=source.path, text=match.text))
        if source.text is not None:
            for match in alias_scanner.find(source.text):
                alias_hits.append(finding("E09", f"«{match.text}»", path=source.path, line=match.line, text=match.text))
    if alias_hits:
        raise ObfuscatorError(alias_hits)

    # §5.6 п. 4: прямая замена текстов и путей.
    per_rule: Counter[str] = Counter()
    per_file: dict[str, int] = {}
    copy_files: dict[str, bytes] = {}
    entries: list[FileEntry] = []
    pairs: list[PathPair] = []
    errors: list[Finding] = []
    warnings: list[Finding] = list(inputs.skipped)
    leak_scanner = Scanner(rule.original for rule in rules)

    for source in sources:
        copy_path = transform_path(source.path, fwd)
        pairs.append(PathPair(original=source.path, copy=copy_path))
        if transform_path(copy_path, bwd) != source.path:
            errors.append(finding("E11", "путь", path=source.path))
        errors.extend(path_leak_findings(leak_scanner, copy_path, source.path, allow, "E12"))
        if source.text is None:
            data = source.data
            warnings.extend(binary_findings(leak_scanner, data, source.path))
        else:
            text, counts = fwd.replace(source.text)
            per_rule.update(counts)
            if counts:
                per_file[source.path] = sum(counts.values())
            if bwd.apply(text) != source.text:
                errors.append(finding("E11", "текст", path=source.path))
            errors.extend(leak_findings(leak_scanner, text, source.path, allow, "E12"))
            data = text.encode("utf-8")
        copy_files[copy_path] = data
        entries.append(
            FileEntry(
                original_path=source.path,
                copy_path=copy_path,
                kind=source.kind,
                original_sha256=sha256_hex(source.data),
                copy_sha256=sha256_hex(data),
            )
        )

    path_errors, path_warnings = check_copy_paths(pairs)
    errors = path_errors + errors
    warnings.extend(path_warnings)
    if errors:
        raise ObfuscatorError(errors)

    # §5.6 п. 7: запись во временные каталоги и замена.
    timestamp = now_iso()
    state = State(
        tool_version=__version__,
        created_at=timestamp,
        updated_at=timestamp,
        root=str(inputs.root),
        inputs=inputs.inputs,
        git=inputs.git,
        dictionary_sha256=dictionary.sha256,
        files=tuple(entries),
    )
    staged_copy = make_staging(out)
    staged_state = make_staging(state_dir)
    try:
        write_tree(staged_copy, copy_files)
        write_tree(staged_state / BASELINE_DIR, copy_files)
        write_state(staged_state, state)
        swap_into_place([(staged_copy, out), (staged_state, state_dir)])
    finally:
        remove_tree(staged_copy)
        remove_tree(staged_state)

    report = Report(command="obfuscate", warnings=warnings)
    report.per_rule = {rule.original: per_rule[rule.original] for rule in rules if per_rule[rule.original]}
    report.per_file = dict(sorted(per_file.items()))
    report.counters = {
        "inputs": len(inputs.inputs),
        "git": int(inputs.git),
        "copied": len(sources),
        "text": sum(1 for s in sources if s.text is not None),
        "binary": sum(1 for s in sources if s.text is None),
        "excluded_ignore": len(inputs.excluded_ignore),
        "excluded_service": len(inputs.excluded_service),
        "skipped": len(inputs.skipped),
        "replacements": sum(per_rule.values()),
        "files_with_replacements": len(per_file),
        "paths_changed": sum(1 for pair in pairs if pair.copy != pair.original),
    }
    report.files = {
        "скопированы": [s.path for s in sources],
        "бинарные": [s.path for s in sources if s.text is None],
        "исключены .obfignore": list(inputs.excluded_ignore),
        "исключены служебные": list(inputs.excluded_service),
    }
    report.locations = {"root": str(inputs.root), "copy": str(out), "state": str(state_dir)}
    return report
