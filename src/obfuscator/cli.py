"""Интерфейс командной строки ``obfuscator``.

Коды выхода (спецификация §7): 0 — успех, 1 — отказ, 2 — ошибка аргументов.
"""

import argparse
import sys
from collections.abc import Sequence

from obfuscator import __version__

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    """Создаёт разборщик аргументов.

    Returns:
        Разборщик с общими параметрами; подкоманды добавляются на этапе 4 плана.
    """
    parser = argparse.ArgumentParser(
        prog="obfuscator",
        description="Лексический обфускатор проекта для безопасной работы с LLM-агентом.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI.

    Args:
        argv: Аргументы без имени программы; ``None`` — взять из ``sys.argv``.

    Returns:
        Код выхода процесса.
    """
    parser = build_parser()
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        parser.parse_args(args)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    return EXIT_OK
