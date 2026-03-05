from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import random


@dataclass
class RogueEnemy:
    x: int
    y: int
    hp: int
    atk: int
    glyph: str = "g"


MOVE_KEYS: dict[str, tuple[int, int]] = {
    "up": (0, -1),
    "w": (0, -1),
    "down": (0, 1),
    "s": (0, 1),
    "left": (-1, 0),
    "a": (-1, 0),
    "right": (1, 0),
    "d": (1, 0),
}


class RoguelikeGame:
    def __init__(self, app: "GethesApp") -> None:
        self.app = app
        self.width = 34
        self.height = 16
        self.max_depth = 5
        self.active = False

        self.depth = 1
        self.max_hp = 26
        self.hp = 26
        self.atk = 5
        self.potions = 2
        self.gold = 0
        self.kills = 0

        self.player_x = 1
        self.player_y = 1
        self.exit_x = 1
        self.exit_y = 1
        self.tiles: list[list[str]] = []
        self.enemies: list[RogueEnemy] = []
        self.items: dict[tuple[int, int], str] = {}
        self.traps: set[tuple[int, int]] = set()
        self.discovered: set[tuple[int, int]] = set()
        self.log_lines: list[str] = []
        self.guard_charges = 0
        self.vision_radius = 5
        self.rng = random.Random()

    def start(self, seed: int | None = None) -> None:
        if self.active:
            return

        if seed is None:
            self.rng.seed()
        else:
            self.rng.seed(int(seed))

        self.active = True
        self.depth = 1
        self.max_hp = 26
        self.hp = self.max_hp
        self.atk = 5
        self.potions = 2
        self.gold = 0
        self.kills = 0
        self.guard_charges = 0
        self.discovered = set()
        self.log_lines = []
        self._generate_floor()
        self._push_log(self.app.tr("game.rogue.floor_start", depth=self.depth))

        self.app.ui.set_entry_enabled(False)
        self.app.ui.set_key_handler(self.handle_key)
        self.app.ui.set_status(self.app.tr("game.rogue.status"))
        self.app.audio.play("success")
        self._render()

    def update(self, _dt: float) -> None:
        if not self.active:
            return

    def handle_key(self, key: str) -> None:
        if not self.active:
            return

        if key in {"q", "escape"}:
            self._finish(
                won=False,
                cancelled=True,
                message=self.app.tr("game.rogue.cancel"),
            )
            return

        if key in {"h"}:
            self._use_potion()
            if self.active:
                self._enemy_turn()
            self._render()
            return

        if key in {"f"}:
            self._focus_guard()
            if self.active:
                self._enemy_turn()
            self._render()
            return

        if key in {"e", "return"}:
            if self.player_x == self.exit_x and self.player_y == self.exit_y and not self.enemies:
                self._descend_or_finish()
            else:
                self._push_log(self.app.tr("game.rogue.stairs_locked"))
            if self.active:
                self._render()
            return

        move = MOVE_KEYS.get(key)
        if move is None:
            return

        moved = self._player_step(move[0], move[1])
        if moved and self.active:
            self._enemy_turn()
        if self.active:
            self._render()

    def _player_step(self, dx: int, dy: int) -> bool:
        tx = self.player_x + dx
        ty = self.player_y + dy
        if not self._is_inside(tx, ty):
            return False
        if self.tiles[ty][tx] == "#":
            self._push_log(self.app.tr("game.rogue.blocked"))
            return False

        enemy = self._enemy_at(tx, ty)
        if enemy is not None:
            self._attack_enemy(enemy)
            return True

        self.player_x = tx
        self.player_y = ty
        self._update_visibility()
        self._trigger_trap(tx, ty)
        if not self.active:
            return True
        self._pickup_item(tx, ty)

        if self.player_x == self.exit_x and self.player_y == self.exit_y and not self.enemies:
            self._push_log(self.app.tr("game.rogue.exit_hint"))
        return True

    def _use_potion(self) -> None:
        if self.potions <= 0:
            self._push_log(self.app.tr("game.rogue.no_potion"))
            return
        if self.hp >= self.max_hp:
            self._push_log(self.app.tr("game.rogue.hp_full"))
            return

        self.potions -= 1
        heal = 6 + self.rng.randint(0, 4)
        before = self.hp
        self.hp = min(self.max_hp, self.hp + heal)
        self._push_log(self.app.tr("game.rogue.use_potion", value=(self.hp - before)))
        self.app.audio.play("success")

    def _focus_guard(self) -> None:
        if self.guard_charges > 0:
            self._push_log(self.app.tr("game.rogue.focus_already"))
            return
        self.guard_charges = 1
        self._push_log(self.app.tr("game.rogue.focus_ready"))
        self.app.audio.play("tick")

    def _attack_enemy(self, enemy: RogueEnemy) -> None:
        damage = self.rng.randint(1, self.atk + 2)
        enemy.hp -= damage
        self._push_log(self.app.tr("game.rogue.hit_enemy", enemy=enemy.glyph, damage=damage))
        self.app.audio.play("hit")
        if enemy.hp > 0:
            return

        self.enemies = [item for item in self.enemies if item is not enemy]
        self.kills += 1
        found = self.rng.randint(2, 8) + self.depth
        if enemy.glyph == "B":
            found += 8 + self.depth
        self.gold += found
        self._push_log(self.app.tr("game.rogue.enemy_down", enemy=enemy.glyph, gold=found))

        if not self.enemies:
            self._push_log(self.app.tr("game.rogue.stairs_ready"))

    def _enemy_turn(self) -> None:
        if not self.active:
            return
        if not self.enemies:
            return

        occupied = {(enemy.x, enemy.y) for enemy in self.enemies}
        occupied.add((self.player_x, self.player_y))
        for enemy in list(self.enemies):
            if not self.active:
                return
            occupied.discard((enemy.x, enemy.y))

            distance = abs(enemy.x - self.player_x) + abs(enemy.y - self.player_y)
            if distance == 1:
                hit = self.rng.randint(1, max(1, enemy.atk))
                if self.guard_charges > 0:
                    reduced = max(1, hit // 2)
                    self._push_log(
                        self.app.tr("game.rogue.guard_block", damage=hit, reduced=reduced)
                    )
                    hit = reduced
                    self.guard_charges = 0
                self.hp -= hit
                self._push_log(self.app.tr("game.rogue.enemy_hit", enemy=enemy.glyph, damage=hit))
                self.app.audio.play("error")
                occupied.add((enemy.x, enemy.y))
                if self.hp <= 0:
                    self._finish(
                        won=False,
                        cancelled=False,
                        message=self.app.tr("game.rogue.lose"),
                    )
                    return
                continue

            if distance > 9:
                occupied.add((enemy.x, enemy.y))
                continue

            step_x = 0
            step_y = 0
            diff_x = self.player_x - enemy.x
            diff_y = self.player_y - enemy.y
            if abs(diff_x) >= abs(diff_y):
                step_x = 1 if diff_x > 0 else (-1 if diff_x < 0 else 0)
            else:
                step_y = 1 if diff_y > 0 else (-1 if diff_y < 0 else 0)

            candidates = [(enemy.x + step_x, enemy.y + step_y)]
            if step_x != 0:
                candidates.append((enemy.x, enemy.y + (1 if diff_y > 0 else -1)))
            if step_y != 0:
                candidates.append((enemy.x + (1 if diff_x > 0 else -1), enemy.y))

            moved = False
            for nx, ny in candidates:
                if not self._is_inside(nx, ny):
                    continue
                if self.tiles[ny][nx] == "#":
                    continue
                if (nx, ny) in occupied:
                    continue
                enemy.x = nx
                enemy.y = ny
                moved = True
                break

            if not moved:
                # keep position when no valid path
                pass
            occupied.add((enemy.x, enemy.y))

    def _trigger_trap(self, x: int, y: int) -> None:
        pos = (x, y)
        if pos not in self.traps:
            return
        self.traps.discard(pos)
        damage = self.rng.randint(2, 3 + max(1, self.depth // 2))
        self.hp -= damage
        self._push_log(self.app.tr("game.rogue.trap_trigger", damage=damage))
        self.app.audio.play("error")
        if self.hp <= 0:
            self._finish(
                won=False,
                cancelled=False,
                message=self.app.tr("game.rogue.lose"),
            )

    def _pickup_item(self, x: int, y: int) -> None:
        item = self.items.pop((x, y), "")
        if item == "gold":
            found = self.rng.randint(5, 13)
            self.gold += found
            self.app.audio.play("tick")
            self._push_log(self.app.tr("game.rogue.pick_gold", value=found))
            return
        if item == "potion":
            self.potions += 1
            self.app.audio.play("success")
            self._push_log(self.app.tr("game.rogue.pick_potion"))
            return
        if item == "relic":
            if self.rng.random() < 0.55:
                gain = 1 + (1 if self.depth >= 4 else 0)
                self.atk += gain
                self._push_log(self.app.tr("game.rogue.pick_relic_atk", value=gain))
            else:
                gain = 2 + (1 if self.depth >= 4 else 0)
                self.max_hp += gain
                self.hp = min(self.max_hp, self.hp + gain)
                self._push_log(self.app.tr("game.rogue.pick_relic_hp", value=gain))
            self.app.audio.play("success")

    def _descend_or_finish(self) -> None:
        if self.depth >= self.max_depth:
            self._finish(
                won=True,
                cancelled=False,
                message=self.app.tr("game.rogue.win"),
            )
            return

        self.depth += 1
        self.hp = min(self.max_hp, self.hp + 4)
        self.guard_charges = 0
        self._generate_floor()
        self._push_log(self.app.tr("game.rogue.next_floor", depth=self.depth))
        self.app.audio.play("success")

    def _generate_floor(self) -> None:
        self.guard_charges = 0
        self.tiles = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                if x == 0 or y == 0 or x == (self.width - 1) or y == (self.height - 1):
                    row.append("#")
                else:
                    row.append(".")
            self.tiles.append(row)

        player_pos = self._random_floor(avoid=set())
        self.player_x, self.player_y = player_pos

        exit_pos = self._random_floor(avoid={player_pos})

        wall_count = 18 + (self.depth * 4)
        attempts = 0
        while wall_count > 0 and attempts < 320:
            attempts += 1
            x = self.rng.randint(1, self.width - 2)
            y = self.rng.randint(1, self.height - 2)
            if (x, y) in {player_pos, exit_pos}:
                continue
            if abs(x - self.player_x) + abs(y - self.player_y) <= 2:
                continue
            if abs(x - exit_pos[0]) + abs(y - exit_pos[1]) <= 2:
                continue
            if self.tiles[y][x] == "#":
                continue
            self.tiles[y][x] = "#"
            wall_count -= 1

        reachable = self._reachable_floor_tiles(start=(self.player_x, self.player_y))
        exit_candidate = self._random_from_pool(reachable, avoid={player_pos})
        if exit_candidate is None:
            self.exit_x, self.exit_y = player_pos
        else:
            self.exit_x, self.exit_y = exit_candidate

        self.items = {}
        self.traps = set()
        item_count = 2 + self.depth
        reserved = {(self.player_x, self.player_y), (self.exit_x, self.exit_y)}
        for _ in range(item_count):
            pos = self._random_from_pool(reachable, avoid=set(self.items.keys()) | reserved)
            if pos is None:
                break
            self.items[pos] = "gold"

        potion_pos = self._random_from_pool(reachable, avoid=set(self.items.keys()) | reserved)
        if potion_pos is not None:
            self.items[potion_pos] = "potion"

        if self.depth >= 2:
            relic_pos = self._random_from_pool(reachable, avoid=set(self.items.keys()) | reserved)
            if relic_pos is not None:
                self.items[relic_pos] = "relic"

        trap_total = min(2 + self.depth, 8)
        for _ in range(trap_total):
            pos = self._random_from_pool(
                reachable,
                avoid=reserved | set(self.items.keys()) | self.traps,
            )
            if pos is None:
                break
            self.traps.add(pos)

        self.enemies = []
        enemy_total = 3 + (self.depth * 2)
        for idx in range(enemy_total):
            glyph, hp, atk = self._enemy_template(idx)
            pos = self._random_from_pool(
                reachable,
                avoid={
                    (self.player_x, self.player_y),
                    (self.exit_x, self.exit_y),
                    *[(enemy.x, enemy.y) for enemy in self.enemies],
                }
                | set(self.items.keys()),
            )
            if pos is None:
                break
            self.enemies.append(RogueEnemy(x=pos[0], y=pos[1], hp=hp, atk=atk, glyph=glyph))
        self.discovered = set()
        self._update_visibility()

    def _enemy_template(self, index: int) -> tuple[str, int, int]:
        if self.depth >= 4 and index == 0:
            return ("B", 8 + (self.depth * 2), 4 + self.depth)
        templates = [
            ("g", 4 + self.depth, 2 + (self.depth // 2)),
            ("s", 3 + self.depth, 3 + (self.depth // 2)),
            ("w", 5 + self.depth, 2 + self.depth),
        ]
        return templates[index % len(templates)]

    def _random_floor(self, avoid: set[tuple[int, int]]) -> tuple[int, int]:
        candidates = []
        for y in range(1, self.height - 1):
            for x in range(1, self.width - 1):
                if self.tiles[y][x] != ".":
                    continue
                if (x, y) in avoid:
                    continue
                candidates.append((x, y))
        if not candidates:
            return 1, 1
        return self.rng.choice(candidates)

    def _random_from_pool(
        self,
        pool: set[tuple[int, int]],
        avoid: set[tuple[int, int]],
    ) -> tuple[int, int] | None:
        candidates = [
            (x, y)
            for x, y in pool
            if (x, y) not in avoid and self.tiles[y][x] == "."
        ]
        if not candidates:
            return None
        return self.rng.choice(candidates)

    def _reachable_floor_tiles(self, start: tuple[int, int]) -> set[tuple[int, int]]:
        sx, sy = start
        if not self._is_inside(sx, sy):
            return set()
        if self.tiles[sy][sx] == "#":
            return set()

        result: set[tuple[int, int]] = set()
        queue = deque([(sx, sy)])
        result.add((sx, sy))
        while queue:
            x, y = queue.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx = x + dx
                ny = y + dy
                if not self._is_inside(nx, ny):
                    continue
                if self.tiles[ny][nx] == "#":
                    continue
                pos = (nx, ny)
                if pos in result:
                    continue
                result.add(pos)
                queue.append(pos)
        return result

    def _visible_tiles(self) -> set[tuple[int, int]]:
        visible: set[tuple[int, int]] = set()
        radius_sq = self.vision_radius * self.vision_radius
        for y in range(self.height):
            for x in range(self.width):
                dx = x - self.player_x
                dy = y - self.player_y
                if (dx * dx) + (dy * dy) <= radius_sq:
                    visible.add((x, y))
        return visible

    def _update_visibility(self) -> None:
        self.discovered.update(self._visible_tiles())

    def _enemy_at(self, x: int, y: int) -> RogueEnemy | None:
        for enemy in self.enemies:
            if enemy.x == x and enemy.y == y:
                return enemy
        return None

    def _is_inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def _push_log(self, message: str) -> None:
        text = message.strip()
        if not text:
            return
        self.log_lines.append(text)
        if len(self.log_lines) > 6:
            self.log_lines = self.log_lines[-6:]

    def _render(self) -> None:
        lines = [
            self.app.tr("game.rogue.title", depth=self.depth, max_depth=self.max_depth),
            self.app.tr(
                "game.rogue.stats",
                hp=max(0, self.hp),
                max_hp=self.max_hp,
                atk=self.atk,
                potions=self.potions,
                gold=self.gold,
                kills=self.kills,
                enemies=len(self.enemies),
                guard=self.guard_charges,
            ),
            self.app.tr("game.rogue.controls"),
            "",
        ]

        board = [row[:] for row in self.tiles]
        board[self.exit_y][self.exit_x] = ">"
        for (x, y), kind in self.items.items():
            if kind == "gold":
                board[y][x] = "$"
            elif kind == "potion":
                board[y][x] = "!"
            elif kind == "relic":
                board[y][x] = "*"
        for x, y in self.traps:
            board[y][x] = "^"
        for enemy in self.enemies:
            board[enemy.y][enemy.x] = enemy.glyph
        board[self.player_y][self.player_x] = "@"

        visible = self._visible_tiles()
        self.discovered.update(visible)
        for y in range(self.height):
            for x in range(self.width):
                pos = (x, y)
                if pos not in self.discovered:
                    board[y][x] = " "
                    continue
                if pos not in visible and board[y][x] not in {"#", ".", " "}:
                    board[y][x] = "."

        lines.append("+" + ("-" * self.width) + "+")
        for row in board:
            lines.append("|" + "".join(row) + "|")
        lines.append("+" + ("-" * self.width) + "+")

        lines.append("")
        lines.append(self.app.tr("game.rogue.log_title"))
        if self.log_lines:
            for entry in self.log_lines[-5:]:
                lines.append(f"- {entry}")
        else:
            lines.append(f"- {self.app.tr('game.rogue.empty_log')}")

        self.app.ui.set_screen("\n".join(lines))

    def _finish(self, won: bool, cancelled: bool, message: str) -> None:
        self.active = False
        self.app.ui.set_key_handler(None)
        self.app.ui.set_entry_enabled(True)
        self.app.ui.set_status(self.app.tr("ui.ready"))

        lines = [
            self.app.tr("game.rogue.summary_title"),
            "==========================================",
            message,
            self.app.tr(
                "game.rogue.summary_line",
                depth=self.depth,
                max_depth=self.max_depth,
                kills=self.kills,
                gold=self.gold,
            ),
            self.app.tr("game.rogue.again"),
        ]
        self.app.ui.set_screen("\n".join(lines))

        if cancelled:
            self.app.audio.play("tick")
        else:
            self.app.audio.play("success" if won else "game_over")

        self.app.on_roguelike_finished(
            won=won,
            cancelled=cancelled,
            depth=self.depth,
            kills=self.kills,
            gold=self.gold,
        )


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gethes.app import GethesApp
