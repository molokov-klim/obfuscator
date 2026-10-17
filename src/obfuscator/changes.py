"""Изменения агента в копии относительно точки отсчёта (спецификация §5.7 п. 5)."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Changes:
    """Изменения копии; пути — относительно копии, разделитель ``/``, каждый список отсортирован.

    Attributes:
        modified: Путь есть в обоих снимках, содержимое разное.
        added: Путь есть только в текущей копии.
        deleted: Путь есть только в точке отсчёта.
        renamed: Пары (старый путь, новый путь) с одинаковым содержимым.
    """

    modified: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    renamed: tuple[tuple[str, str], ...] = ()

    @property
    def empty(self) -> bool:
        """Нет ни одного изменения."""
        return not (self.modified or self.added or self.deleted or self.renamed)


def detect_changes(baseline: Mapping[str, str], current: Mapping[str, str]) -> Changes:
    """Сравнивает снимки «путь → хэш содержимого».

    Удалённый и добавленный файлы с одинаковым хэшем считаются переименованием; пары составляются детерминированно
    в порядке путей.

    Args:
        baseline: Снимок точки отсчёта.
        current: Текущая копия.

    Returns:
        Изменения.
    """
    modified = sorted(path for path in baseline.keys() & current.keys() if baseline[path] != current[path])
    deleted = sorted(baseline.keys() - current.keys())
    added = sorted(current.keys() - baseline.keys())

    added_by_hash: dict[str, list[str]] = {}
    for path in added:
        added_by_hash.setdefault(current[path], []).append(path)

    renamed: list[tuple[str, str]] = []
    still_deleted: list[str] = []
    for path in deleted:
        candidates = added_by_hash.get(baseline[path])
        if candidates:
            renamed.append((path, candidates.pop(0)))
        else:
            still_deleted.append(path)
    renamed_targets = {new for _, new in renamed}
    return Changes(
        modified=tuple(modified),
        added=tuple(path for path in added if path not in renamed_targets),
        deleted=tuple(still_deleted),
        renamed=tuple(renamed),
    )
