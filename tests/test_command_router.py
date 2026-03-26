from __future__ import annotations

from gethes.application.command_router import CommandRouter


def test_command_router_dispatch_normalizes_alias() -> None:
    calls: list[tuple[list[str], str, list[str]]] = []
    router = CommandRouter()
    router.add(" Help ", lambda args, raw, parts: calls.append((args, raw, parts)))

    handled = router.dispatch("HELP", ["topic"], "help topic", ["help", "topic"])
    assert handled is True
    assert calls == [(["topic"], "help topic", ["help", "topic"])]


def test_command_router_add_many_registers_all_aliases() -> None:
    hits: list[str] = []
    router = CommandRouter()
    router.add_many({"exit", "salir", "quit"}, lambda _args, raw, _parts: hits.append(raw))

    assert router.dispatch("salir", [], "salir", ["salir"]) is True
    assert router.dispatch("quit", [], "quit", ["quit"]) is True
    assert router.dispatch("desconocido", [], "desconocido", ["desconocido"]) is False
    assert hits == ["salir", "quit"]
    assert {"exit", "salir", "quit"}.issubset(router.aliases)
