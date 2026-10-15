"""Каталог состояния `<копия>.obfstate/` (спецификация §4.1.3)."""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from obfuscator.errors import ObfuscatorError
from obfuscator.models import FileEntry, FileKind
from obfuscator.narrow import as_list, as_table

STATE_SUFFIX = ".obfstate"
STATE_FILE = "state.json"
BASELINE_DIR = "baseline"
FORMAT = 1


@dataclass(frozen=True)
class State:
    """Содержимое `state.json`.

    Attributes:
        tool_version: Версия инструмента, записавшего состояние.
        created_at: Время обфускации, ISO 8601 с часовым поясом.
        updated_at: Время последнего сдвига точки отсчёта.
        root: Абсолютный путь корня входа.
        inputs: Пути входа относительно корня, разделитель ``/``.
        git: Вход под git.
        dictionary_sha256: Хэш файла словаря.
        files: Файлы точки отсчёта.
    """

    tool_version: str
    created_at: str
    updated_at: str
    root: str
    inputs: tuple[str, ...]
    git: bool
    dictionary_sha256: str
    files: tuple[FileEntry, ...]


def sha256_hex(data: bytes) -> str:
    """Возвращает SHA-256 в шестнадцатеричном виде.

    Args:
        data: Байты.

    Returns:
        Хэш.
    """
    return hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    """Возвращает текущее время в ISO 8601 с локальным часовым поясом, до секунд.

    Returns:
        Строка времени.
    """
    return datetime.now().astimezone().isoformat(timespec="seconds")


def state_dir_for(copy_dir: Path) -> Path:
    """Возвращает каталог состояния для каталога копии.

    Args:
        copy_dir: Каталог копии.

    Returns:
        ``<копия>.obfstate`` рядом с копией.
    """
    return copy_dir.with_name(copy_dir.name + STATE_SUFFIX)


def to_json(state: State) -> str:
    """Сериализует состояние.

    Args:
        state: Состояние.

    Returns:
        JSON с отступами, ключи в порядке спецификации, не-ASCII без экранирования.
    """
    document = {
        "format": FORMAT,
        "tool_version": state.tool_version,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "root": state.root,
        "inputs": list(state.inputs),
        "git": state.git,
        "dictionary_sha256": state.dictionary_sha256,
        "files": [
            {
                "original_path": f.original_path,
                "copy_path": f.copy_path,
                "kind": f.kind,
                "original_sha256": f.original_sha256,
                "copy_sha256": f.copy_sha256,
            }
            for f in state.files
        ],
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def from_json(text: str) -> State:
    """Разбирает и проверяет `state.json`.

    Args:
        text: Содержимое файла.

    Returns:
        Состояние.

    Raises:
        ObfuscatorError: E20 — не JSON, неизвестный формат или неверные поля.
    """

    def fail(detail: str) -> ObfuscatorError:
        return ObfuscatorError.single("E20", f"{STATE_FILE}: {detail}")

    try:
        raw: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise fail(f"не JSON: {exc}") from exc
    document = as_table(raw)
    if document is None:
        raise fail("ожидается объект")
    if document.get("format") != FORMAT:
        raise fail(f"неподдерживаемый формат {document.get('format')!r}, ожидается {FORMAT}")

    def text_field(table: dict[str, object], key: str) -> str:
        value = table.get(key)
        if not isinstance(value, str):
            raise fail(f"поле {key} должно быть строкой")
        return value

    git = document.get("git")
    if not isinstance(git, bool):
        raise fail("поле git должно быть true или false")
    inputs = as_list(document.get("inputs"))
    if inputs is None or not all(isinstance(i, str) for i in inputs):
        raise fail("поле inputs должно быть списком строк")
    raw_files = as_list(document.get("files"))
    if raw_files is None:
        raise fail("поле files должно быть списком")

    files: list[FileEntry] = []
    for item in raw_files:
        entry = as_table(item)
        if entry is None:
            raise fail("элемент files должен быть объектом")
        raw_kind = entry.get("kind")
        kind: FileKind
        if raw_kind == "text":
            kind = "text"
        elif raw_kind == "binary":
            kind = "binary"
        else:
            raise fail(f"неверный kind {raw_kind!r}")
        files.append(
            FileEntry(
                original_path=text_field(entry, "original_path"),
                copy_path=text_field(entry, "copy_path"),
                kind=kind,
                original_sha256=text_field(entry, "original_sha256"),
                copy_sha256=text_field(entry, "copy_sha256"),
            )
        )

    return State(
        tool_version=text_field(document, "tool_version"),
        created_at=text_field(document, "created_at"),
        updated_at=text_field(document, "updated_at"),
        root=text_field(document, "root"),
        inputs=tuple(str(i) for i in inputs),
        git=git,
        dictionary_sha256=text_field(document, "dictionary_sha256"),
        files=tuple(files),
    )


def read_state(state_dir: Path) -> State:
    """Читает состояние из каталога.

    Args:
        state_dir: Каталог состояния.

    Returns:
        Состояние.

    Raises:
        ObfuscatorError: E20 — каталог или файл не найден, не читается или повреждён.
    """
    path = state_dir / STATE_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ObfuscatorError.single("E20", f"нет {path}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ObfuscatorError.single("E20", f"не удалось прочитать {path}: {exc}") from exc
    return from_json(text)


def write_state(state_dir: Path, state: State) -> None:
    """Атомарно записывает `state.json`: временный файл рядом и переименование.

    Args:
        state_dir: Каталог состояния; создаётся при необходимости.
        state: Состояние.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    target = state_dir / STATE_FILE
    temporary = state_dir / f".{STATE_FILE}.tmp"
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(to_json(state))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
