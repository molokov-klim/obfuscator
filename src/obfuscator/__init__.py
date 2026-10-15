"""Лексический обфускатор проекта для безопасной работы с LLM-агентом."""

from importlib.metadata import version

__version__ = version("obfuscator")

__all__ = ["__version__"]
