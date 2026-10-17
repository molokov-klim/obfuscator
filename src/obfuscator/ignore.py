"""Исключения `.obfignore` с семантикой `.gitignore` (спецификация §3.3)."""

from pathlib import Path

import pathspec

from obfuscator.errors import ObfuscatorError

IGNORE_FILE = ".obfignore"


class IgnoreRules:
    """Правила всех `.obfignore` под корнем; файлы читаются по мере надобности и кэшируются.

    Путь проверяется сверху вниз: сначала каждый каталог-предок (исключённый каталог исключает всё внутри, вернуть
    файл из него `!`-шаблоном нельзя — как в git), затем сам путь. Для каждой проверки решает самый глубокий
    `.obfignore` среди каталогов-предков, у которого есть подходящий шаблон.
    """

    def __init__(self, root: Path) -> None:
        """Создаёт набор правил.

        Args:
            root: Корень входа.
        """
        self.root = root
        self._specs: dict[str, pathspec.GitIgnoreSpec | None] = {}

    def _spec(self, directory: str) -> pathspec.GitIgnoreSpec | None:
        if directory not in self._specs:
            path = self.root / directory / IGNORE_FILE if directory else self.root / IGNORE_FILE
            spec: pathspec.GitIgnoreSpec | None = None
            if path.is_file():
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                    spec = pathspec.GitIgnoreSpec.from_lines(lines)
                except (OSError, UnicodeDecodeError, ValueError) as exc:
                    shown = f"{directory}/{IGNORE_FILE}" if directory else IGNORE_FILE
                    raise ObfuscatorError.single("E13", f"{shown}: {exc}") from exc
            self._specs[directory] = spec
        return self._specs[directory]

    def _decides(self, path: str, is_dir: bool) -> bool | None:
        parts = path.split("/")
        # Каталоги, чьи .obfignore могут касаться пути: корень и все предки, кроме самого пути.
        for depth in range(len(parts) - 1, -1, -1):
            directory = "/".join(parts[:depth])
            spec = self._spec(directory)
            if spec is None:
                continue
            relative = "/".join(parts[depth:]) + ("/" if is_dir else "")
            include = spec.check_file(relative).include
            if include is not None:
                return include
        return None

    def is_excluded(self, path: str, *, is_dir: bool = False) -> bool:
        """Проверяет путь относительно корня.

        Args:
            path: Путь с разделителем ``/``.
            is_dir: Путь — каталог.

        Returns:
            ``True``, если путь или один из его каталогов-предков исключён.
        """
        parts = path.split("/")
        for depth in range(1, len(parts)):
            if self._decides("/".join(parts[:depth]), is_dir=True):
                return True
        return bool(self._decides(path, is_dir))
