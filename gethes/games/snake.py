from __future__ import annotations

from collections import deque
import random
import time


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
        self.foods: list[Point] = []
        self.food_target = 1
        self.mode = "classic"
        self.difficulty = "normal"
        self.score = 0
        self.level = 1
        self.paused = False
        self.active = False
        self.tick_accumulator = 0.0
        self.pending_directions: deque[Direction] = deque(maxlen=6)
        self.foods_eaten = 0
        self.rng = random.Random()
        self._last_pause_toggle_at = 0.0

    def start(
        self,
        seed: int | None = None,
        *,
        difficulty: str = "normal",
        mode: str = "classic",
        apples: int = 0,
    ) -> None:
        if self.active:
            return

        self.difficulty = self._normalize_difficulty(difficulty)
        self.mode = self._normalize_mode(mode)
        self.food_target = self._resolve_food_target(apples=apples)

        if seed is None:
            self.rng.seed()
        else:
            self.rng.seed(int(seed))

        cx = self.width // 2
        cy = self.height // 2
        self.snake = [(cx, cy), (cx - 1, cy), (cx - 2, cy)]
        self.direction = (1, 0)
        self.foods = []
        self._spawn_foods_until_target()
        self.score = 0
        self.level = 1
        self.paused = False
        self.active = True
        self.tick_accumulator = 0.0
        self.pending_directions.clear()
        self.foods_eaten = 0
        self._last_pause_toggle_at = 0.0

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
            now = time.monotonic()
            if (now - self._last_pause_toggle_at) < 0.18:
                return
            self._last_pause_toggle_at = now
            self.paused = not self.paused
            self._render()
            return

        new_direction = DIRECTION_KEYS.get(key)
        if not new_direction:
            return

        current = self.pending_directions[-1] if self.pending_directions else self.direction
        if new_direction == OPPOSITE_DIRECTION[current]:
            return

        self.pending_directions.append(new_direction)

    def _tick_delay_ms(self) -> int:
        base_delays = {
            "low": 230,
            "medium": 160,
            "high": 95,
        }
        base = base_delays.get(self.app.config.graphics, 160)
        difficulty_boost = {
            "easy": 0.86,
            "normal": 1.0,
            "hard": 1.2,
            "insane": 1.38,
        }.get(self.difficulty, 1.0)
        reduction = min(75, max(0, (self.level - 1) * 7))
        adjusted = int((base - reduction) / difficulty_boost)
        return max(45, adjusted)

    def _tick_once(self) -> None:
        if not self.active:
            return

        next_direction = self.direction
        while self.pending_directions:
            candidate = self.pending_directions.popleft()
            if candidate != OPPOSITE_DIRECTION[next_direction]:
                # Apply the freshest valid input in the same frame for smoother turns.
                next_direction = candidate
        self.direction = next_direction

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

        if self.mode == "online":
            ghost_fn = getattr(self.app, "get_snake_online_ghosts", None)
            sync_fn = getattr(self.app, "get_snake_online_sync_meta", None)
            sync_ok = True
            if callable(sync_fn):
                _ping, age_seconds, fail_streak = sync_fn()
                if age_seconds > 6 or fail_streak >= 3:
                    sync_ok = False
            if callable(ghost_fn) and sync_ok:
                for gx, gy, _name in ghost_fn():
                    if (gx, gy) == new_head:
                        self._finish(self.app.tr("game.snake.hit_rival"), game_over=True)
                        return

        self.snake.insert(0, new_head)
        if new_head in self.foods:
            self.foods = [food for food in self.foods if food != new_head]
            base_gain = 10
            mode_bonus = 3 if self.mode == "multiapple" else 0
            difficulty_bonus = {
                "easy": 0,
                "normal": 1,
                "hard": 2,
                "insane": 3,
            }.get(self.difficulty, 1)
            self.score += base_gain + mode_bonus + difficulty_bonus
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
            self._spawn_foods_until_target()
        else:
            self.snake.pop()

        self._render()

    def _spawn_food(self) -> Point:
        available = [
            (x, y)
            for y in range(self.height)
            for x in range(self.width)
            if (x, y) not in self.snake and (x, y) not in self.foods
        ]
        return self.rng.choice(available)

    def _spawn_foods_until_target(self) -> None:
        while len(self.foods) < self.food_target:
            self.foods.append(self._spawn_food())

    @staticmethod
    def _normalize_difficulty(token: str) -> str:
        value = token.strip().lower()
        if value in {"easy", "facil", "fÃ¡cil", "e"}:
            return "easy"
        if value in {"hard", "dificil", "difÃ­cil", "h"}:
            return "hard"
        if value in {"insane", "extreme", "extremo", "impossible", "nightmare", "x"}:
            return "insane"
        return "normal"

    @staticmethod
    def _normalize_mode(token: str) -> str:
        value = token.strip().lower()
        if value in {"multi", "multiapple", "multimanzana", "manzanas", "apples"}:
            return "multiapple"
        if value in {"online", "arena", "multiplayer", "mp", "slither", "slitherio", "agar", "agario", "io"}:
            return "online"
        return "classic"

    def _resolve_food_target(self, *, apples: int) -> int:
        if self.mode == "multiapple":
            if apples > 0:
                return max(2, min(7, int(apples)))
            return 3
        if self.mode == "online":
            return 2
        return 1

    def _render(self, message: str = "") -> None:
        board = [[" " for _ in range(self.width)] for _ in range(self.height)]
        for bx, by in self.snake[1:]:
            board[by][bx] = "o"

        hx, hy = self.snake[0]
        board[hy][hx] = "@"
        for fx, fy in self.foods:
            board[fy][fx] = "*"
        if self.mode == "online":
            ghost_fn = getattr(self.app, "get_snake_online_ghosts", None)
            if callable(ghost_fn):
                for gx, gy, _name in ghost_fn():
                    if (gx, gy) == (hx, hy):
                        continue
                    if 0 <= gx < self.width and 0 <= gy < self.height and board[gy][gx] == " ":
                        board[gy][gx] = "+"

        mode_text = {
            "classic": "CLASSIC",
            "multiapple": "MULTI",
            "online": "ONLINE",
        }.get(self.mode, "CLASSIC")
        diff_text = self.difficulty.upper()

        lines = [
            f"{self.app.tr('game.snake.title', score=self.score, level=self.level)} | {mode_text} | {diff_text}",
            self.app.tr(
                "game.snake.best",
                score=self.app.get_stat("snake_best_score"),
                level=self.app.get_stat("snake_best_level"),
            ),
            self.app.tr("game.snake.foods", count=self.foods_eaten),
        ]
        if self.mode == "online":
            count_fn = getattr(self.app, "get_snake_online_player_count", None)
            if callable(count_fn):
                lines.append(self.app.tr("game.snake.online_players", count=int(count_fn())))
            room_fn = getattr(self.app, "get_snake_online_room", None)
            sync_fn = getattr(self.app, "get_snake_online_sync_meta", None)
            rank_fn = getattr(self.app, "get_snake_online_rank", None)
            room_value = "global"
            ping_ms = 0
            age_seconds = 0
            if callable(room_fn):
                room_value = str(room_fn()).strip() or "global"
            if callable(sync_fn):
                ping_ms, age_seconds, _ = sync_fn()
            rank_value = int(rank_fn() or 0) if callable(rank_fn) else 0
            lines.append(
                self.app.tr(
                    "game.snake.online_status",
                    room=room_value,
                    ping=max(0, int(ping_ms)),
                    sync=max(0, int(age_seconds)),
                    rank=rank_value if rank_value > 0 else "-",
                )
            )
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
            panel_lines = [
                f"SCORE {self.score} | LVL {self.level}",
                f"MODE {mode_text} | {diff_text}",
                self.app.tr("game.snake.foods", count=self.foods_eaten),
            ]
            if self.mode == "online":
                count_fn = getattr(self.app, "get_snake_online_player_count", None)
                if callable(count_fn):
                    panel_lines.append(self.app.tr("game.snake.online_compact", count=int(count_fn())))
                room_fn = getattr(self.app, "get_snake_online_room", None)
                sync_fn = getattr(self.app, "get_snake_online_sync_meta", None)
                if callable(room_fn) and callable(sync_fn):
                    ping_ms, age_seconds, _ = sync_fn()
                    panel_lines.append(
                        self.app.tr(
                            "game.snake.online_panel",
                            room=str(room_fn()).strip() or "global",
                            ping=max(0, int(ping_ms)),
                            sync=max(0, int(age_seconds)),
                        )
                    )
            panel_fn(
                "snake",
                current_lines=panel_lines,
            )

    def _finish(self, message: str, game_over: bool, user_exit: bool = False) -> None:
        self.active = False
        self.paused = False
        self.tick_accumulator = 0.0
        self.pending_directions.clear()

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

