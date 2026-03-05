from __future__ import annotations

import random


WIN_LINES = [
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
]


class TicTacToeGame:
    def __init__(self, app: "GethesApp") -> None:
        self.app = app
        self.board = [str(i) for i in range(1, 10)]
        self.active = False
        self.winning_line: tuple[int, int, int] | None = None

    def start(self) -> None:
        self.active = True
        self.board = [str(i) for i in range(1, 10)]
        self.winning_line = None
        self.app.set_input_handler(self._handle_move)
        self.app.ui.set_status(self.app.tr("game.ttt.status"))
        self.app.audio.play("success")
        self._render()

    def _handle_move(self, raw: str) -> None:
        move = raw.strip().lower()
        if move in {"exit", "salir", "quit", "sair"}:
            self._finish(self.app.tr("game.ttt.cancel"), finished=False)
            return

        if not move.isdigit():
            self._render(message=self.app.tr("game.ttt.invalid"))
            return

        index = int(move) - 1
        if index < 0 or index > 8 or self.board[index] in {"X", "O"}:
            self._render(message=self.app.tr("game.ttt.invalid"))
            return

        self.board[index] = "X"
        player_line = self._winner_line("X")
        if player_line:
            self.winning_line = player_line
            self._finish(self.app.tr("game.ttt.player_win"), finished=True, won=True)
            return

        if self._is_draw():
            self._finish(self.app.tr("game.ttt.draw"), finished=True, draw=True)
            return

        self._cpu_move()
        cpu_line = self._winner_line("O")
        if cpu_line:
            self.winning_line = cpu_line
            self._finish(self.app.tr("game.ttt.cpu_win"), finished=True, won=False)
            return

        if self._is_draw():
            self._finish(self.app.tr("game.ttt.draw"), finished=True, draw=True)
            return

        self._render()

    def _cpu_move(self) -> None:
        available = [i for i, value in enumerate(self.board) if value not in {"X", "O"}]
        if not available:
            return

        best_score = -999
        best_moves: list[int] = []
        for index in available:
            self.board[index] = "O"
            score = self._minimax(depth=0, is_cpu_turn=False)
            self.board[index] = str(index + 1)
            if score > best_score:
                best_score = score
                best_moves = [index]
            elif score == best_score:
                best_moves.append(index)

        pick = random.choice(best_moves or available)
        self.board[pick] = "O"
        self.app.audio.play("tick")

    def _minimax(self, depth: int, is_cpu_turn: bool) -> int:
        if self._winner_line("O"):
            return 10 - depth
        if self._winner_line("X"):
            return depth - 10
        if self._is_draw():
            return 0

        available = [i for i, value in enumerate(self.board) if value not in {"X", "O"}]
        if is_cpu_turn:
            best = -999
            for index in available:
                self.board[index] = "O"
                best = max(best, self._minimax(depth + 1, is_cpu_turn=False))
                self.board[index] = str(index + 1)
            return best

        best = 999
        for index in available:
            self.board[index] = "X"
            best = min(best, self._minimax(depth + 1, is_cpu_turn=True))
            self.board[index] = str(index + 1)
        return best

    def _winner_line(self, mark: str) -> tuple[int, int, int] | None:
        for line in WIN_LINES:
            if all(self.board[pos] == mark for pos in line):
                return line
        return None

    def _is_draw(self) -> bool:
        return all(value in {"X", "O"} for value in self.board)

    def _refresh_action_buttons(self) -> None:
        buttons: list[tuple[str, str, bool]] = []
        for idx, value in enumerate(self.board, start=1):
            occupied = value in {"X", "O"}
            label = value if occupied else str(idx)
            buttons.append((label, str(idx), not occupied))
        buttons.append((self.app.tr("ui.action.exit"), "exit", True))
        self.app.ui.set_action_buttons(buttons)

    def _render(self, message: str = "") -> None:
        b = self.board
        board_text = "\n".join(
            [
                f" {b[0]} | {b[1]} | {b[2]} ",
                "---+---+---",
                f" {b[3]} | {b[4]} | {b[5]} ",
                "---+---+---",
                f" {b[6]} | {b[7]} | {b[8]} ",
            ]
        )

        lines = [
            self.app.tr("game.ttt.title"),
            "==========================================",
            self.app.tr("game.ttt.info"),
            self.app.tr("game.ttt.controls"),
            "",
            board_text,
        ]
        if message:
            lines.extend(["", message])
        if self.winning_line:
            line_values = [str(value + 1) for value in self.winning_line]
            lines.append(self.app.tr("game.ttt.win_line", cells=", ".join(line_values)))
        self.app.ui.set_screen("\n".join(lines))
        self._refresh_action_buttons()

    def _finish(self, message: str, finished: bool, won: bool = False, draw: bool = False) -> None:
        self.active = False
        self.app.clear_input_handler()
        self.app.ui.set_status(self.app.tr("ui.ready"))
        lines = [
            self.app.tr("game.ttt.title"),
            "==========================================",
            "",
            message,
            self.app.tr("game.ttt.again"),
        ]
        self.app.ui.set_screen("\n".join(lines))
        if finished:
            self.app.audio.play("success" if won else "game_over")
            self.app.on_tictactoe_finished(won=won, draw=draw)
        else:
            self.app.audio.play("tick")


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gethes.app import GethesApp
