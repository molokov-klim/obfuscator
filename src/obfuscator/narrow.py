"""Сужение типов для данных из `tomllib` и `json`: они возвращают непроверенные структуры."""

from typing import cast


def as_table(value: object) -> dict[str, object] | None:
    """Возвращает таблицу TOML или ``None``.

    Args:
        value: Значение из ``tomllib``.

    Returns:
        Таблица с ключами-строками или ``None``, если это не таблица.
    """
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return None


def as_list(value: object) -> list[object] | None:
    """Возвращает массив TOML или ``None``.

    Args:
        value: Значение из ``tomllib``.

    Returns:
        Список или ``None``, если это не массив.
    """
    if isinstance(value, list):
        return cast("list[object]", value)
    return None
