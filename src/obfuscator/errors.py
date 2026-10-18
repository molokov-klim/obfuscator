"""Коды ошибок и предупреждений (спецификация §7) и исключение отказа."""

from collections.abc import Iterable

from obfuscator.models import Finding

ERRORS: dict[str, str] = {
    "E01": "словарь не задан, не найден, не TOML или неверная схема",
    "E02": "словарь пуст",
    "E03": "недопустимый оригинал или алиас",
    "E04": "повтор алиаса",
    "E05": "алиас — подстрока другого алиаса",
    "E06": "алиас содержит оригинал",
    "E07": "недопустимый вход",
    "E08": "недопустимый каталог копии",
    "E09": "алиас встречается в проекте",
    "E10": "недопустимый путь копии",
    "E11": "обратная замена не даёт оригинал",
    "E12": "утечка оригинала в копию",
    "E13": "неверный формат .obfallow.toml или .obfignore",
    "E14": "неверное правило по словам",
    "E20": "состояние не найдено или повреждено",
    "E21": "словарь изменился после обфускации",
    "E22": "оригинал изменился после точки отсчёта",
    "E23": "незакоммиченные изменения в путях входа",
    "E24": "--worktree для входа не под git",
    "E25": "новый файл агента совпадает с существующим файлом оригинала",
    "E26": "git не найден или завершился ошибкой",
    "E27": "недопустимый путь патча",
    "E28": "ошибка записи в оригинал; изменения откатаны",
}

WARNINGS: dict[str, str] = {
    "W01": "оригинал в байтах бинарного файла",
    "W02": "путь оригинала уже недопустим на Windows",
    "W03": "пропущена символическая ссылка или подмодуль",
    "W04": "правило подстроки с коротким оригиналом",
    "W10": "оригинал в изменениях агента",
    "W11": "алиас в другом регистре, не восстановлен",
    "W12": "агент удалил файл",
    "W13": "агент переименовал файл",
    "W14": "агент изменил или добавил бинарный файл",
}


def finding(
    code: str,
    detail: str = "",
    *,
    path: str | None = None,
    line: int | None = None,
    text: str | None = None,
) -> Finding:
    """Создаёт находку с заголовком кода и уточнением.

    Args:
        code: Код из ``ERRORS`` или ``WARNINGS``.
        detail: Уточнение; добавляется после заголовка через двоеточие.
        path: Путь оригинала относительно корня.
        line: Номер строки с 1.
        text: Найденное написание.

    Returns:
        Находка.

    Raises:
        KeyError: Неизвестный код.
    """
    title = ERRORS[code] if code in ERRORS else WARNINGS[code]
    message = f"{title}: {detail}" if detail else title
    return Finding(code=code, message=message, path=path, line=line, text=text)


class ObfuscatorError(Exception):
    """Отказ: одна или несколько ошибок с E-кодами."""

    def __init__(self, findings: Iterable[Finding]) -> None:
        """Создаёт исключение.

        Args:
            findings: Ошибки; не пусто.

        Raises:
            ValueError: Список пуст.
        """
        self.findings: list[Finding] = list(findings)
        if not self.findings:
            raise ValueError("ObfuscatorError требует хотя бы одну находку")
        super().__init__("; ".join(f"{f.code} {f.message}" for f in self.findings))

    @classmethod
    def single(
        cls,
        code: str,
        detail: str = "",
        *,
        path: str | None = None,
        line: int | None = None,
        text: str | None = None,
    ) -> "ObfuscatorError":
        """Создаёт исключение с одной ошибкой.

        Args:
            code: E-код.
            detail: Уточнение.
            path: Путь оригинала относительно корня.
            line: Номер строки с 1.
            text: Найденное написание.

        Returns:
            Исключение.
        """
        return cls([finding(code, detail, path=path, line=line, text=text)])
