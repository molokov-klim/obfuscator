"""Интерфейс командной строки ``obfuscator``.

Коды выхода (спецификация §7): 0 — успех, 1 — отказ, 2 — ошибка аргументов.
"""

import argparse
import io
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from obfuscator import __version__
from obfuscator.dictionary import load_dictionary, resolve_dictionary_path
from obfuscator.errors import ObfuscatorError
from obfuscator.gitio import Git, SubprocessGit
from obfuscator.models import Finding
from obfuscator.obfuscate import run_obfuscate
from obfuscator.report import format_obfuscate, format_refusal, format_restore, summary_lines
from obfuscator.restore import Mode, run_restore

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    """Создаёт разборщик аргументов.

    Returns:
        Разборщик с подкомандами.
    """
    parser = argparse.ArgumentParser(
        prog="obfuscator",
        description="Лексический обфускатор проекта для безопасной работы с LLM-агентом.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="КОМАНДА")

    obfuscate = commands.add_parser("obfuscate", help="построить обфусцированную копию")
    obfuscate.add_argument("paths", nargs="+", type=Path, metavar="PATH", help="файлы и каталоги входа")
    obfuscate.add_argument("--out", required=True, type=Path, metavar="DIR", help="каталог копии")
    obfuscate.add_argument("--dict", dest="dictionary", metavar="FILE", help="словарь (иначе OBFUSCATOR_DICT)")
    obfuscate.add_argument("--verbose", action="store_true", help="подробности по файлам")

    restore = commands.add_parser("restore", help="вернуть изменения агента в оригинал")
    restore.add_argument("copy", type=Path, metavar="COPY_DIR", help="каталог копии")
    how = restore.add_mutually_exclusive_group(required=True)
    how.add_argument("--worktree", action="store_true", help="записать в рабочее дерево оригинала (только git)")
    how.add_argument("--patch", type=Path, metavar="FILE", help="записать патч для git apply")
    restore.add_argument("--dict", dest="dictionary", metavar="FILE", help="словарь (иначе OBFUSCATOR_DICT)")
    restore.add_argument("--verbose", action="store_true", help="списки файлов")
    return parser


def _print_findings(items: list[Finding], stream: TextIO, *, verbose: bool = False) -> None:
    for line in summary_lines(items, verbose=verbose):
        print(line, file=stream)


def _obfuscate(args: argparse.Namespace, git: Git) -> int:
    dictionary_arg: str | None = args.dictionary
    paths: list[Path] = args.paths
    out: Path = args.out
    verbose: bool = args.verbose
    dictionary = load_dictionary(resolve_dictionary_path(dictionary_arg))
    report = run_obfuscate(paths, out, dictionary, git)
    sys.stdout.write(format_obfuscate(report, {r.original: r.alias for r in dictionary.rules}, verbose=verbose))
    _print_findings(report.warnings, sys.stderr, verbose=verbose)
    return EXIT_OK


def _restore(args: argparse.Namespace, git: Git) -> int:
    dictionary_arg: str | None = args.dictionary
    copy: Path = args.copy
    patch: Path | None = args.patch
    verbose: bool = args.verbose
    mode: Mode = "patch" if patch is not None else "worktree"
    dictionary = load_dictionary(resolve_dictionary_path(dictionary_arg))
    report = run_restore(copy, mode, dictionary, git, patch_file=patch)
    sys.stdout.write(format_restore(report, mode, verbose=verbose))
    _print_findings(report.warnings, sys.stderr, verbose=verbose)
    return EXIT_OK


def main(argv: Sequence[str] | None = None, *, git: Git | None = None) -> int:
    """Точка входа CLI.

    Args:
        argv: Аргументы без имени программы; ``None`` — взять из ``sys.argv``.
        git: Порт git; ``None`` — программа ``git``.

    Returns:
        Код выхода процесса.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            # Отчёт на русском: на Windows вывод в канал иначе идёт в кодировке ANSI и падает на кириллице.
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args_list = list(sys.argv[1:] if argv is None else argv)
    if not args_list:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        args = parser.parse_args(args_list)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    command: str | None = args.command
    if command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        port = git or SubprocessGit()
        return _obfuscate(args, port) if command == "obfuscate" else _restore(args, port)
    except ObfuscatorError as error:
        verbose = bool(getattr(args, "verbose", False))
        sys.stdout.write(format_refusal(f"obfuscator {command}", error.findings, verbose=verbose))
        _print_findings(error.findings, sys.stderr, verbose=verbose)
        return EXIT_REFUSED
