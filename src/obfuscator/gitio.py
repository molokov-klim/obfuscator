"""Доступ к git (спецификация §4.2.2): порт для сценариев и реализация через подпроцесс."""

import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from obfuscator.errors import ObfuscatorError

# Настройки, которые не должны менять поведение инструмента у разных пользователей.
SAFE_CONFIG = (
    "-c",
    "core.quotePath=false",
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.safecrlf=false",
    "-c",
    "color.ui=false",
)


class Git(Protocol):
    """Операции git, нужные сценариям; все только читают репозиторий пользователя."""

    def toplevel(self, directory: Path) -> Path | None:
        """Корень рабочего дерева, содержащего каталог, или ``None`` вне репозитория."""
        ...

    def tracked_files(self, root: Path, pathspecs: Sequence[str]) -> list[str]:
        """Отслеживаемые пути внутри ``pathspecs`` (относительно корня, разделитель ``/``)."""
        ...

    def status(self, root: Path, pathspecs: Sequence[str]) -> list[str]:
        """Записи ``git status --porcelain`` внутри ``pathspecs``; пусто — чисто."""
        ...

    def is_ignored(self, root: Path, path: str) -> bool:
        """Игнорируется ли путь (может не существовать) правилами `.gitignore`."""
        ...

    def make_patch(self, before: Mapping[str, bytes], after: Mapping[str, bytes | None]) -> bytes:
        """Патч ``git diff --binary`` от ``before`` к ``after`` (``None`` — удаление); пути относительно корня."""
        ...


class SubprocessGit:
    """Реализация порта через программу ``git``."""

    def __init__(self, executable: str = "git") -> None:
        """Создаёт адаптер.

        Args:
            executable: Имя или путь программы git.
        """
        self.executable = executable

    def run_raw(self, args: Sequence[str], *, cwd: Path | None = None) -> tuple[int, bytes, str]:
        """Запускает git без проверки кода выхода.

        Args:
            args: Аргументы после ``git`` и безопасных настроек.
            cwd: Рабочий каталог.

        Returns:
            Код выхода, stdout, stderr (текстом).

        Raises:
            ObfuscatorError: E26 — программа git не найдена.
        """
        command = [self.executable, *SAFE_CONFIG, *args]
        try:
            result = subprocess.run(command, cwd=cwd, capture_output=True, check=False)
        except FileNotFoundError as exc:
            raise ObfuscatorError.single("E26", f"программа {self.executable} не найдена") from exc
        return result.returncode, result.stdout, result.stderr.decode("utf-8", errors="replace").strip()

    def run(self, args: Sequence[str], *, cwd: Path | None = None, ok_codes: Sequence[int] = (0,)) -> bytes:
        """Запускает git и возвращает stdout.

        Args:
            args: Аргументы после ``git`` и безопасных настроек.
            cwd: Рабочий каталог.
            ok_codes: Коды выхода, которые не считаются ошибкой.

        Returns:
            Байты stdout.

        Raises:
            ObfuscatorError: E26 — git не найден или вернул код вне ``ok_codes``.
        """
        code, stdout, stderr = self.run_raw(args, cwd=cwd)
        if code not in ok_codes:
            raise ObfuscatorError.single("E26", f"git {' '.join(args)}: код {code}: {stderr}")
        return stdout

    def toplevel(self, directory: Path) -> Path | None:
        """Корень рабочего дерева или ``None`` вне репозитория.

        Args:
            directory: Существующий каталог.

        Returns:
            Абсолютный путь корня или ``None``.

        Raises:
            ObfuscatorError: E26 — git не найден: без него нельзя отличить проект под git и не скопировать лишнее.
        """
        code, stdout, _ = self.run_raw(["-C", str(directory), "rev-parse", "--show-toplevel"])
        if code != 0:
            return None
        return Path(os.fsdecode(stdout.strip()))

    def tracked_files(self, root: Path, pathspecs: Sequence[str]) -> list[str]:
        """Отслеживаемые пути (``ls-files``) с буквальными путями.

        Args:
            root: Корень репозитория.
            pathspecs: Пути входа относительно корня.

        Returns:
            Пути относительно корня, разделитель ``/``.
        """
        out = self.run(["--literal-pathspecs", "ls-files", "-z", "--cached", "--", *pathspecs], cwd=root)
        return [os.fsdecode(item) for item in out.split(b"\0") if item]

    def status(self, root: Path, pathspecs: Sequence[str]) -> list[str]:
        """Незакоммиченные изменения в путях.

        Args:
            root: Корень репозитория.
            pathspecs: Пути входа относительно корня.

        Returns:
            Записи ``status --porcelain=v1 -z``.
        """
        out = self.run(
            ["--literal-pathspecs", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *pathspecs],
            cwd=root,
        )
        return [os.fsdecode(item) for item in out.split(b"\0") if item]

    def is_ignored(self, root: Path, path: str) -> bool:
        """Проверяет путь правилами `.gitignore` без учёта индекса.

        Args:
            root: Корень репозитория.
            path: Путь относительно корня.

        Returns:
            ``True``, если путь игнорируется.

        Raises:
            ObfuscatorError: E26 — ошибка git.
        """
        code, _, stderr = self.run_raw(["check-ignore", "-q", "--no-index", "--", path], cwd=root)
        if code not in (0, 1):
            raise ObfuscatorError.single("E26", f"git check-ignore: код {code}: {stderr}")
        return code == 0

    def make_patch(self, before: Mapping[str, bytes], after: Mapping[str, bytes | None]) -> bytes:
        """Строит патч во временном репозитории (спецификация §4.2.2).

        Args:
            before: Затронутые файлы оригинала: путь → байты.
            after: Новые версии: путь → байты или ``None`` для удаления.

        Returns:
            Патч в формате ``git diff --binary``; пустые байты — изменений нет.

        Raises:
            ObfuscatorError: E26 — ошибка git.
        """
        identity = ("-c", "user.name=obfuscator", "-c", "user.email=obfuscator@localhost", "-c", "commit.gpgsign=false")
        with tempfile.TemporaryDirectory(prefix="obfuscator-patch-") as directory:
            work = Path(directory)
            self.run(["init", "-q"], cwd=work)
            for relative, data in before.items():
                target = work / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            self.run(["add", "-A", "--force"], cwd=work)
            self.run([*identity, "commit", "-q", "--allow-empty", "--no-verify", "-m", "base"], cwd=work)
            for relative, data in after.items():
                target = work / relative
                if data is None:
                    target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
            self.run(["add", "-A", "--force"], cwd=work)
            return self.run(["diff", "--cached", "--binary", "--no-color", "--no-renames", "--no-ext-diff"], cwd=work)
