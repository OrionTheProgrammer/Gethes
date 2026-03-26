from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Callable


CommandHandler = Callable[[list[str], str, list[str]], None]


@dataclass
class CommandRouter:
    _handlers: dict[str, CommandHandler] = field(default_factory=dict)

    def add(self, alias: str, handler: CommandHandler) -> None:
        token = alias.strip().lower()
        if not token:
            return
        self._handlers[token] = handler

    def add_many(self, aliases: Iterable[str], handler: CommandHandler) -> None:
        for alias in aliases:
            self.add(alias, handler)

    def dispatch(self, alias: str, args: list[str], raw_command: str, parts: list[str]) -> bool:
        token = alias.strip().lower()
        if not token:
            return False
        handler = self._handlers.get(token)
        if handler is None:
            return False
        handler(args, raw_command, parts)
        return True

    @property
    def aliases(self) -> set[str]:
        return set(self._handlers.keys())
