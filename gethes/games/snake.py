from __future__ import annotations

import random


Direction = tuple[int, int]
Point = tuple[int, int]


DIRECTION_KEYS: dict[str, Direction] = {
    "up": (0, -1),
    "w": (0, -1),
    "down": (0, 1),
    "s": (0, 1),
    "left": (-1, 0),
    "a": (-1, 0),
    "right": (1, 0),
    "d": (1, 0),
}

OPPOSITE_DIRECTION: dict[Direction, Direction] = {
    (0, -1): (0, 1),
    (0, 1): (0, -1),
    (-1, 0): (1, 0),
    (1, 0): (-1, 0),
}


class SnakeGame:
    def __init__(self, app: "GethesApp") -> None:
        self.app = app
        self.width = 28
        self.height = 16
        self.snake: list[Point] = []
        self.direction: Direction = (1, 0)
        self.food: Point = (0, 0)
        self.score = 0
        self.level = 1
        self.paused = False
        self.active = False
        self.tick_accumulator = 0.0
        self.pending_direction: Direction | None = None
        self.foods_eaten = 0
        self.rng = random.Random()

    def start(self, seed: int | None = None) -> None:
        if self.active:
            return

        if seed is None:
            self.rng.seed()
        else:
            self.rng.seed(int(seed))

        cx = self.width // 2
        cy = self.height // 2
        self.snake = [(cx, cy), (cx - 1, cy), (cx - 2, cy)]
        self.direction = (1, 0)
        self.food = self._spawn_food()
        self.score = 0
        self.level = 1
        self.paused = False
        self.active = True
        self.tick_accumulator = 0.0
        self.pending_direction = None
        self.foods_eaten = 0

        self.app.audio.play("success")
        self.app.ui.set_entry_enabled(False)
        self.app.ui.set_key_handler(self.handle_key)
        self.app.ui.set_status(self.app.tr("game.snake.status"))
        self._render()

    def update(self, dt: float) -> None:
        if not self.active or self.paused:
            return

        self.tick_accumulator += dt * 1000.0
        tick_ms = self._tick_delay_ms()
        while self.tick_accumulator >= tick_ms and self.active:
            self.tick_accumulator -= tick_ms
            self._tick_once()
            tick_ms = self._tick_delay_ms()

    def handle_key(self, key: str) -> None:
        if not self.active:
            return

        if key in {"q", "escape"}:
            self._finish(self.app.tr("game.snake.user_exit"), game_over=False, user_exit=True)
            return

        if key == "p":
            self.paused = not self.paused
            self._render()
            return

        new_direction = DIRECTION_KEYS.get(key)
        if not new_direction:
            return

        current = self.pending_direction or self.direction
        if new_direction == OPPOSITE_DIRECTION[current]:
            return

        self.pending_direction = new_direction

    def _tick_delay_ms(self) -> int:
        base_delays = {
            "low": 230,
            "medium": 160,
            "high": 95,
        }
        base = base_delays.get(self.app.config.graphics, 160)
        reduction = min(70, max(0, (self.level - 1) * 7))
        return max(55, base - reduction)

    def _tick_once(self) -> None:
        if not self.active:
            return

        if self.pending_direction is not None:
            if self.pending_direction != OPPOSITE_DIRECTION[self.direction]:
                self.direction = self.pending_direction
            self.pending_direction = None

        head_x, head_y = self.snake[0]
        dx, dy = self.direction
        new_head = (head_x + dx, head_y + dy)

        x, y = new_head
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            self._finish(self.app.tr("game.snake.hit_wall"), game_over=True)
            return

        if new_head in self.snake:
            self._finish(self.app.tr("game.snake.hit_tail"), game_over=True)
            return

        self.snake.insert(0, new_head)
        if new_head == self.food:
            self.score += 10
            self.level = 1 + (self.score // 40)
            self.foods_eaten += 1
            self.app.audio.play("hit")
            self.app.on_snake_food_eaten(
                score=self.score,
                level=self.level,
                length=len(self.snake),
            )
            if len(self.snake) == self.width * self.height:
                self._finish(self.app.tr("game.snake.win_full"), game_over=False)
                return
            self.food = self._spawn_food()
        else:
            self.snake.pop()

        self._render()

    def _spawn_food(self) -> Point:
        available = [
            (x, y)
            for y in range(self.height)
            for x in range(self.width)
            if (x, y) not in self.snake
        ]
        return self.rng.choice(available)

    def _render(self, message: str = "") -> None:
        board = [[" " for _ in range(self.width)] for _ in range(self.height)]
        for bx, by in self.snake[1:]:
            board[by][bx] = "o"

        hx, hy = self.snake[0]
        board[hy][hx] = "@"
        fx, fy = self.food
        board[fy][fx] = "*"

        lines = [
            self.app.tr("game.snake.title", score=self.score, level=self.level),
            self.app.tr(
                "game.snake.best",
                score=self.app.get_stat("snake_best_score"),
                level=self.app.get_stat("snake_best_level"),
            ),
            self.app.tr("game.snake.foods", count=self.foods_eaten),
        ]
        lines.append(
            self.app.tr("game.snake.state.pause")
            if self.paused
            else self.app.tr("game.snake.state.play")
        )
        lines.append(self.app.tr("game.snake.controls"))
        lines.append("")
        lines.append("+" + ("-" * self.width) + "+")
        for row in board:
            lines.append("|" + "".join(row) + "|")
        lines.append("+" + ("-" * self.width) + "+")
        if message:
            lines.append("")
            lines.append(message)
            lines.append(self.app.tr("game.snake.again"))

        self.app.ui.set_screen("\n".join(lines))
        panel_fn = getattr(self.app, "set_live_leaderboard_panel", None)
        if callable(panel_fn):
            panel_fn(
                "snake",
                current_lines=[
                    self.app.tr("game.snake.title", score=self.score, level=self.level),
                    self.app.tr("game.snake.foods", count=self.foods_eaten),
                ],
            )

    def _finish(self, message: str, game_over: bool, user_exit: bool = False) -> None:
        self.active = False
        self.paused = False
        self.tick_accumulator = 0.0
        self.pending_direction = None

        self.app.ui.set_key_handler(None)
        self.app.ui.set_entry_enabled(True)
        self.app.ui.set_status(self.app.tr("ui.ready"))
        self._render(message=message)
        clear_panel_fn = getattr(self.app, "clear_live_leaderboard_panel", None)
        if callable(clear_panel_fn):
            clear_panel_fn()
        self.app.audio.play("game_over" if game_over else "success")
        self.app.on_snake_finished(
            score=self.score,
            level=self.level,
            foods_eaten=self.foods_eaten,
            game_over=game_over,
            user_exit=user_exit,
        )


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gethes.app import GethesApp
