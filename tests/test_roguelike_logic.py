from __future__ import annotations

from collections import deque
from types import SimpleNamespace

from gethes.games.roguelike import RoguelikeGame


class _DummyAudio:
    def __init__(self) -> None:
        self.events: list[str] = []

    def play(self, event: str) -> None:
        self.events.append(event)


class _DummyUI:
    def __init__(self) -> None:
        self.status = ""
        self.screen = ""
        self.entry_enabled = True
        self.key_handler = None

    def set_entry_enabled(self, value: bool) -> None:
        self.entry_enabled = value

    def set_key_handler(self, handler) -> None:  # type: ignore[no-untyped-def]
        self.key_handler = handler

    def set_status(self, value: str) -> None:
        self.status = value

    def set_screen(self, value: str) -> None:
        self.screen = value


class _DummyApp:
    def __init__(self) -> None:
        self.audio = _DummyAudio()
        self.ui = _DummyUI()
        self.finish_calls: list[dict[str, object]] = []
        self.config = SimpleNamespace(graphics="medium")

    def tr(self, key: str, **kwargs: object) -> str:
        if not kwargs:
            return key
        parts = ", ".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return f"{key} ({parts})"

    def on_roguelike_finished(
        self,
        won: bool,
        cancelled: bool,
        depth: int,
        kills: int,
        gold: int,
    ) -> None:
        self.finish_calls.append(
            {
                "won": won,
                "cancelled": cancelled,
                "depth": depth,
                "kills": kills,
                "gold": gold,
            }
        )


def test_roguelike_start_builds_valid_floor() -> None:
    app = _DummyApp()
    game = RoguelikeGame(app)
    game.rng.seed(7)
    game.start()

    assert game.active is True
    assert len(game.tiles) == game.height
    assert len(game.tiles[0]) == game.width
    assert (game.player_x, game.player_y) != (game.exit_x, game.exit_y)
    assert len(game.enemies) >= 1
    assert app.ui.entry_enabled is False
    assert app.ui.key_handler is not None


def test_roguelike_blocked_move_does_not_change_position() -> None:
    app = _DummyApp()
    game = RoguelikeGame(app)
    game.rng.seed(3)
    game.start()

    game.player_x = 1
    game.player_y = 1
    game.handle_key("left")
    assert (game.player_x, game.player_y) == (1, 1)
    assert any("game.rogue.blocked" in line for line in game.log_lines)


def test_roguelike_descend_when_exit_ready() -> None:
    app = _DummyApp()
    game = RoguelikeGame(app)
    game.rng.seed(9)
    game.start()

    game.enemies = []
    game.player_x = game.exit_x
    game.player_y = game.exit_y
    game.handle_key("e")
    assert game.active is True
    assert game.depth == 2


def test_roguelike_cancel_reports_finish() -> None:
    app = _DummyApp()
    game = RoguelikeGame(app)
    game.start()

    game.handle_key("q")
    assert game.active is False
    assert app.finish_calls
    assert app.finish_calls[-1]["cancelled"] is True


def test_roguelike_exit_and_enemies_are_reachable() -> None:
    app = _DummyApp()
    game = RoguelikeGame(app)
    game.rng.seed(21)
    game.start()

    visited: set[tuple[int, int]] = set()
    queue = deque([(game.player_x, game.player_y)])
    visited.add((game.player_x, game.player_y))
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx = x + dx
            ny = y + dy
            if not (0 <= nx < game.width and 0 <= ny < game.height):
                continue
            if game.tiles[ny][nx] == "#":
                continue
            pos = (nx, ny)
            if pos in visited:
                continue
            visited.add(pos)
            queue.append(pos)

    assert (game.exit_x, game.exit_y) in visited
    for enemy in game.enemies:
        assert (enemy.x, enemy.y) in visited
