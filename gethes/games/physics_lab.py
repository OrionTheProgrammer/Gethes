from __future__ import annotations

from dataclasses import dataclass

try:
    import pymunk
except Exception:  # pragma: no cover - optional dependency.
    pymunk = None


@dataclass
class PhysicsWorldBounds:
    min_x: float = 20.0
    max_x: float = 400.0
    min_y: float = 20.0
    max_y: float = 290.0


class PhysicsLabGame:
    def __init__(self, app: "GethesApp") -> None:
        self.app = app
        self.active = False

        self.bounds = PhysicsWorldBounds()
        self.world_w = 420.0
        self.world_h = 300.0
        self.grid_w = 30
        self.grid_h = 14

        self.space = None
        self.ball_body = None
        self.ball_shape = None
        self.scored_current_ball = False

        self.score = 0
        self.launches = 0
        self.step_accumulator = 0.0
        self.render_accumulator = 0.0

    @staticmethod
    def dependency_available() -> bool:
        return pymunk is not None

    def start(self) -> None:
        if self.active:
            return
        if pymunk is None:
            self.app.ui.write(self.app.tr("game.physics.dep_missing"))
            return

        self.active = True
        self.score = 0
        self.launches = 0
        self.step_accumulator = 0.0
        self.render_accumulator = 0.0
        self._build_world()
        self._spawn_ball(play_sound=False)

        self.app.ui.set_entry_enabled(False)
        self.app.ui.set_key_handler(self.handle_key)
        self.app.ui.set_status(self.app.tr("game.physics.status"))
        self.app.audio.play("success")
        self._render()

    def update(self, dt: float) -> None:
        if not self.active or self.space is None:
            return

        self.step_accumulator += dt
        fixed_step = 1.0 / 120.0
        while self.step_accumulator >= fixed_step and self.active:
            self.step_accumulator -= fixed_step
            self.space.step(fixed_step)
            self._update_ball_state()

        self.render_accumulator += dt
        if self.render_accumulator >= 0.05:
            self.render_accumulator = 0.0
            self._render()

    def handle_key(self, key: str) -> None:
        if not self.active:
            return

        if key in {"q", "escape"}:
            self._finish(
                self.app.tr("game.physics.quit"),
                won=False,
                cancelled=True,
            )
            return

        if key == "r":
            self._build_world()
            self._spawn_ball(play_sound=True)
            self._render(self.app.tr("game.physics.reset"))
            return

        if key == "space":
            self._spawn_ball(play_sound=True)
            self._render(self.app.tr("game.physics.new_ball"))
            return

        if self.ball_body is None:
            return

        if key in {"left", "a"}:
            self.ball_body.apply_impulse_at_local_point((-180, 0))
            self.app.audio.play("tick")
            return
        if key in {"right", "d"}:
            self.ball_body.apply_impulse_at_local_point((180, 0))
            self.app.audio.play("tick")
            return
        if key in {"up", "w"}:
            self.ball_body.apply_impulse_at_local_point((0, 260))
            self.app.audio.play("tick")
            return

    def _build_world(self) -> None:
        if pymunk is None:
            return

        self.space = pymunk.Space()
        self.space.gravity = (0.0, -900.0)
        self.ball_body = None
        self.ball_shape = None
        self.scored_current_ball = False

        static_body = self.space.static_body
        floor = pymunk.Segment(static_body, (self.bounds.min_x, self.bounds.min_y), (self.bounds.max_x, self.bounds.min_y), 2.0)
        wall_left = pymunk.Segment(static_body, (self.bounds.min_x, self.bounds.min_y), (self.bounds.min_x, self.bounds.max_y), 2.0)
        wall_right = pymunk.Segment(static_body, (self.bounds.max_x, self.bounds.min_y), (self.bounds.max_x, self.bounds.max_y), 2.0)
        ramp = pymunk.Segment(static_body, (200.0, 90.0), (285.0, 130.0), 2.0)
        bumper = pymunk.Circle(static_body, radius=12.0, offset=(250.0, 185.0))

        for shape in (floor, wall_left, wall_right, ramp, bumper):
            shape.elasticity = 0.72
            shape.friction = 0.85
            self.space.add(shape)

    def _spawn_ball(self, play_sound: bool) -> None:
        if pymunk is None or self.space is None:
            return

        if self.ball_shape is not None and self.ball_body is not None:
            try:
                self.space.remove(self.ball_shape, self.ball_body)
            except Exception:
                pass

        radius = 11.0
        mass = 1.0
        inertia = pymunk.moment_for_circle(mass, 0.0, radius)
        body = pymunk.Body(mass, inertia)
        body.position = (68.0, 238.0)
        shape = pymunk.Circle(body, radius)
        shape.elasticity = 0.65
        shape.friction = 0.9
        self.space.add(body, shape)

        self.ball_body = body
        self.ball_shape = shape
        self.scored_current_ball = False
        self.launches += 1
        if play_sound:
            self.app.audio.play("success")

    def _update_ball_state(self) -> None:
        if self.ball_body is None:
            return

        pos = self.ball_body.position
        vel = self.ball_body.velocity
        if self._is_scoring_pose(pos.x, pos.y, vel.y) and not self.scored_current_ball:
            self.scored_current_ball = True
            self.score += 1
            self.app.audio.play("hit")
            if self.score >= 5:
                self._finish(self.app.tr("game.physics.win"), won=True, cancelled=False)
                return
            self._spawn_ball(play_sound=False)
            return

        if pos.y < -25.0:
            self.app.audio.play("error")
            self._spawn_ball(play_sound=False)

    @staticmethod
    def _is_scoring_pose(x: float, y: float, vy: float) -> bool:
        return 332.0 <= x <= 388.0 and y <= 38.0 and abs(vy) < 90.0

    def _render(self, message: str = "") -> None:
        grid = [[" " for _ in range(self.grid_w)] for _ in range(self.grid_h)]

        for x in range(self.grid_w):
            grid[0][x] = "-"
        target_start = int((334.0 / self.world_w) * self.grid_w)
        target_end = int((388.0 / self.world_w) * self.grid_w)
        for x in range(max(0, target_start), min(self.grid_w, target_end + 1)):
            grid[0][x] = "="

        for dx in range(8):
            ox = 12 + dx
            oy = 4 + (dx // 2)
            if 0 <= ox < self.grid_w and 0 <= oy < self.grid_h:
                grid[oy][ox] = "/"

        if self.ball_body is not None:
            gx, gy = self._to_grid(self.ball_body.position.x, self.ball_body.position.y)
            if 0 <= gx < self.grid_w and 0 <= gy < self.grid_h:
                grid[gy][gx] = "O"

        best = self.app.get_stat("physics_best_score", 0)
        lines = [
            self.app.tr("game.physics.title", score=self.score, best=best, launches=self.launches),
            self.app.tr("game.physics.controls"),
            "",
            "+" + ("-" * self.grid_w) + "+",
        ]
        for row in reversed(grid):
            lines.append("|" + "".join(row) + "|")
        lines.append("+" + ("-" * self.grid_w) + "+")
        lines.append(self.app.tr("game.physics.goal"))

        if message:
            lines.extend(["", message])

        self.app.ui.set_screen("\n".join(lines))

    def _to_grid(self, x: float, y: float) -> tuple[int, int]:
        gx = int((x / self.world_w) * (self.grid_w - 1))
        gy = int((y / self.world_h) * (self.grid_h - 1))
        return gx, gy

    def _finish(self, message: str, won: bool, cancelled: bool) -> None:
        self.active = False
        self.step_accumulator = 0.0
        self.render_accumulator = 0.0
        self.app.ui.set_key_handler(None)
        self.app.ui.set_entry_enabled(True)
        self.app.ui.set_status(self.app.tr("ui.ready"))

        lines = [
            self.app.tr("game.physics.summary_title"),
            "==========================================",
            message,
            self.app.tr("game.physics.again"),
        ]
        self.app.ui.set_screen("\n".join(lines))
        self.app.audio.play("success" if won else "tick")
        self.app.on_physics_finished(score=self.score, won=won, cancelled=cancelled)


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gethes.app import GethesApp
