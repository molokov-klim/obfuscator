"""Сценарий возврата (спецификация §5.7)."""

import os
import tempfile
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from obfuscator import __version__
from obfuscator.allow import load_allow
from obfuscator.changes import detect_changes
from obfuscator.dictionary import Dictionary
from obfuscator.errors import ObfuscatorError, finding
from obfuscator.fsio import make_staging, read_tree, remove_tree, swap_into_place, write_tree
from obfuscator.gitio import Git
from obfuscator.ignore import IgnoreRules
from obfuscator.inputs import SERVICE_NAMES, resolve_inputs
from obfuscator.merge import MergeResult, merge_text, restore_new_text
from obfuscator.models import FileEntry, FileKind, Finding, Report
from obfuscator.paths import transform_path
from obfuscator.replacer import backward
from obfuscator.scanner import Scanner, case_mismatch_findings, leak_findings, path_leak_findings
from obfuscator.state import BASELINE_DIR, State, now_iso, read_state, sha256_hex, state_dir_for, write_state

Mode = Literal["worktree", "patch"]


@dataclass
class Plan:
    """Что записать в оригинал.

    Attributes:
        writes: Путь оригинала → новые байты.
        deletes: Пути оригинала к удалению.
        entries: Новая точка отсчёта: путь копии → запись.
        warnings: Предупреждения возврата.
        restored: Число обратных замен по алиасам.
        not_transferred: Новые файлы агента, которые не переносятся.
        counts: Счётчики изменений.
    """

    writes: dict[str, bytes] = field(default_factory=dict[str, bytes])
    deletes: list[str] = field(default_factory=list[str])
    entries: dict[str, FileEntry] = field(default_factory=dict[str, FileEntry])
    warnings: list[Finding] = field(default_factory=list[Finding])
    restored: Counter[str] = field(default_factory=Counter[str])
    not_transferred: list[str] = field(default_factory=list[str])
    counts: Counter[str] = field(default_factory=Counter[str])


def _decode(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _within_inputs(path: str, inputs: tuple[str, ...]) -> bool:
    return any(item == "." or path == item or path.startswith(item + "/") for item in inputs)


def _check_original(state: State, dictionary: Dictionary, copy_dir: Path, state_dir: Path, git: Git) -> None:
    """FR-036: файлы оригинала в путях входа не менялись после точки отсчёта.

    Raises:
        ObfuscatorError: E22 со списком расхождений.
    """
    root = Path(state.root)
    paths = [root if item == "." else root / item for item in state.inputs]
    missing_inputs = [str(path) for path in paths if not path.exists()]
    if missing_inputs:
        raise ObfuscatorError.single("E22", f"нет путей входа: {', '.join(missing_inputs)}")
    current = resolve_inputs(paths, git, protected=[dictionary.path, copy_dir, state_dir])
    expected = {entry.original_path: entry.original_sha256 for entry in state.files}
    problems: list[Finding] = []
    for path in sorted(set(current.files) | set(expected)):
        if path not in expected:
            problems.append(finding("E22", "новый файл", path=path))
        elif path not in current.files:
            problems.append(finding("E22", "файл удалён или исключён", path=path))
        elif sha256_hex((root / path).read_bytes()) != expected[path]:
            problems.append(finding("E22", "файл изменён", path=path))
    if problems:
        raise ObfuscatorError(problems)


def _plan(state: State, dictionary: Dictionary, copy_dir: Path, state_dir: Path, git: Git) -> Plan:
    root = Path(state.root)
    rules = dictionary.rules
    bwd = backward(rules)
    allow = load_allow(root)
    leak_scanner = Scanner(rule.original for rule in rules)
    aliases = frozenset(rule.alias for rule in rules)
    alias_scanner = Scanner(aliases)
    ignore = IgnoreRules(root)
    by_copy = {entry.copy_path: entry for entry in state.files}

    baseline_files = read_tree(state_dir / BASELINE_DIR)
    current_files = read_tree(copy_dir)
    changes = detect_changes(
        {path: sha256_hex(data) for path, data in baseline_files.items()},
        {path: sha256_hex(data) for path, data in current_files.items()},
    )
    plan = Plan()
    for entry in state.files:
        plan.entries[entry.copy_path] = entry

    def warn_new_lines(result: MergeResult, original_path: str) -> None:
        text = "".join(line for _, line in result.new_lines)
        numbers = [number for number, _ in result.new_lines]
        for item in leak_findings(leak_scanner, text, original_path, allow, "W10") + case_mismatch_findings(
            alias_scanner, aliases, text, original_path
        ):
            line = numbers[item.line - 1] if item.line is not None and item.line <= len(numbers) else item.line
            plan.warnings.append(replace(item, line=line))

    def transferable(copy_path: str) -> str | None:
        """Путь оригинала для нового файла агента или ``None``, если файл не переносится (FR-039)."""
        original_path = transform_path(copy_path, bwd)
        name = original_path.rsplit("/", 1)[-1]
        if (
            name in SERVICE_NAMES
            or not _within_inputs(original_path, state.inputs)
            or ignore.is_excluded(original_path)
            or (state.git and git.is_ignored(root, original_path))
        ):
            plan.not_transferred.append(original_path)
            return None
        if (root / original_path).exists() or (root / original_path).is_symlink():
            raise ObfuscatorError.single("E25", "файл уже существует в оригинале", path=original_path)
        plan.warnings.extend(path_leak_findings(leak_scanner, copy_path, original_path, allow, "W10"))
        plan.warnings.extend(case_mismatch_findings(alias_scanner, aliases, copy_path, original_path))
        return original_path

    def record(copy_path: str, original_path: str, data: bytes, kind: FileKind) -> None:
        plan.writes[original_path] = data
        plan.entries[copy_path] = FileEntry(
            original_path=original_path,
            copy_path=copy_path,
            kind=kind,
            original_sha256=sha256_hex(data),
            copy_sha256=sha256_hex(current_files[copy_path]),
        )

    for copy_path in changes.modified:
        entry = by_copy[copy_path]
        data = current_files[copy_path]
        text = _decode(data)
        if entry.kind == "text" and text is not None:
            original_text = (root / entry.original_path).read_bytes().decode("utf-8")
            result = merge_text(original_text, baseline_files[copy_path].decode("utf-8"), text, bwd)
            plan.restored.update(result.restored)
            warn_new_lines(result, entry.original_path)
            record(copy_path, entry.original_path, result.text.encode("utf-8"), "text")
        else:
            plan.warnings.append(finding("W14", "изменён", path=entry.original_path))
            record(copy_path, entry.original_path, data, "binary")
        plan.counts["modified"] += 1

    for copy_path in changes.deleted:
        entry = by_copy[copy_path]
        plan.deletes.append(entry.original_path)
        del plan.entries[copy_path]
        plan.warnings.append(finding("W12", "", path=entry.original_path))
        plan.counts["deleted"] += 1

    for old_copy, new_copy in changes.renamed:
        entry = by_copy[old_copy]
        del plan.entries[old_copy]
        plan.deletes.append(entry.original_path)
        target = transferable(new_copy)
        if target is None:
            plan.warnings.append(finding("W12", "", path=entry.original_path))
            plan.counts["deleted"] += 1
            continue
        plan.warnings.append(finding("W13", f"→ {target}", path=entry.original_path))
        record(new_copy, target, (root / entry.original_path).read_bytes(), entry.kind)
        plan.counts["renamed"] += 1

    for copy_path in changes.added:
        target = transferable(copy_path)
        if target is None:
            continue
        data = current_files[copy_path]
        text = _decode(data)
        if text is None:
            plan.warnings.append(finding("W14", "добавлен", path=target))
            record(copy_path, target, data, "binary")
        else:
            result = restore_new_text(text, bwd)
            plan.restored.update(result.restored)
            warn_new_lines(result, target)
            record(copy_path, target, result.text.encode("utf-8"), "text")
        plan.counts["added"] += 1

    plan.counts["not_transferred"] = len(plan.not_transferred)
    return plan


def _apply_worktree(root: Path, plan: Plan) -> None:
    """Пишет изменения в рабочее дерево; при ошибке откатывает уже сделанное (NFR-011).

    Raises:
        ObfuscatorError: E28.
    """
    backups: dict[str, bytes | None] = {}
    try:
        for relative, data in plan.writes.items():
            target = root / relative
            backups[relative] = target.read_bytes() if target.exists() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix=f".{target.name}.tmp-", dir=target.parent)
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
            os.replace(temporary, target)
        for relative in plan.deletes:
            target = root / relative
            if relative not in backups:
                backups[relative] = target.read_bytes()
            target.unlink()
    except OSError as exc:
        for relative, data in backups.items():
            target = root / relative
            try:
                if data is None:
                    target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
            except OSError:
                continue
        raise ObfuscatorError.single("E28", str(exc)) from exc
    for relative in plan.deletes:
        directory = (root / relative).parent
        while directory != root and directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
            directory = directory.parent


def run_restore(
    copy_dir: Path, mode: Mode, dictionary: Dictionary, git: Git, *, patch_file: Path | None = None
) -> Report:
    """Возвращает изменения агента из копии в оригинал.

    Args:
        copy_dir: Каталог копии.
        mode: ``worktree`` — способ A, ``patch`` — способ B.
        dictionary: Словарь (тот же, что при обфускации).
        git: Порт git.
        patch_file: Файл патча для способа B.

    Returns:
        Отчёт об успешном возврате.

    Raises:
        ObfuscatorError: Любой отказ §5.7; оригинал и состояние при этом не меняются.
    """
    copy_dir = copy_dir.resolve()
    state_dir = state_dir_for(copy_dir)
    if not copy_dir.is_dir():
        raise ObfuscatorError.single("E20", f"нет каталога копии {copy_dir}")
    state = read_state(state_dir)
    if dictionary.sha256 != state.dictionary_sha256:
        raise ObfuscatorError.single("E21", f"{dictionary.path} отличается от словаря обфускации")
    if mode == "worktree" and not state.git:
        raise ObfuscatorError.single("E24", "вход не под git — используйте --patch")
    if mode == "patch":
        if patch_file is None:
            raise ObfuscatorError.single("E27", "не задан файл патча")
        patch_file = patch_file.resolve()
        if patch_file.exists():
            raise ObfuscatorError.single("E27", f"файл уже существует: {patch_file}")
        for forbidden in (copy_dir, state_dir):
            if forbidden in patch_file.parents:
                raise ObfuscatorError.single("E27", f"патч внутри {forbidden}: в нём оригиналы")

    root = Path(state.root)
    _check_original(state, dictionary, copy_dir, state_dir, git)
    if mode == "worktree":
        dirty = git.status(root, state.inputs)
        if dirty:
            raise ObfuscatorError([finding("E23", entry) for entry in dirty])

    plan = _plan(state, dictionary, copy_dir, state_dir, git)
    report = Report(command="restore", warnings=plan.warnings)
    report.counters = {
        "modified": plan.counts["modified"],
        "added": plan.counts["added"],
        "deleted": plan.counts["deleted"],
        "renamed": plan.counts["renamed"],
        "not_transferred": plan.counts["not_transferred"],
        "restored": sum(plan.restored.values()),
    }
    report.files = {"не перенесены": sorted(plan.not_transferred)}
    report.locations = {"root": str(root), "copy": str(copy_dir), "state": str(state_dir)}
    if not plan.writes and not plan.deletes:
        return report

    entries = tuple(sorted(plan.entries.values(), key=lambda entry: entry.copy_path))
    new_state = State(
        tool_version=__version__,
        created_at=state.created_at,
        updated_at=now_iso(),
        root=state.root,
        inputs=state.inputs,
        git=state.git,
        dictionary_sha256=state.dictionary_sha256,
        files=entries,
    )
    current_files = read_tree(copy_dir)
    staged_state = make_staging(state_dir)
    try:
        write_tree(staged_state / BASELINE_DIR, {entry.copy_path: current_files[entry.copy_path] for entry in entries})
        write_state(staged_state, new_state)
        if mode == "worktree":
            _apply_worktree(root, plan)
        else:
            assert patch_file is not None
            touched = set(plan.writes) | set(plan.deletes)
            before = {path: (root / path).read_bytes() for path in sorted(touched) if (root / path).is_file()}
            after: dict[str, bytes | None] = {path: None for path in plan.deletes}
            after.update(plan.writes)
            patch = git.make_patch(before, after)
            patch_file.parent.mkdir(parents=True, exist_ok=True)
            patch_file.write_bytes(patch)
            report.locations["patch"] = str(patch_file)
        swap_into_place([(staged_state, state_dir)])
    finally:
        remove_tree(staged_state)
    return report
