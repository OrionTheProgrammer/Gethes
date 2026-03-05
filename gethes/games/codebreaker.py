from __future__ import annotations

import random


class CodeBreakerGame:
    def __init__(self, app: "GethesApp") -> None:
        self.app = app
        self.secret = ""
        self.attempts_left = 0
        self.max_attempts = 0
        self.active = False
        self.history: list[str] = []
        self.hint_used = False

    def start(self) -> None:
        if self.active:
            return

        self.secret = self._generate_secret()
        self.max_attempts = self._attempts_by_graphics()
        self.attempts_left = self.max_attempts
        self.active = True
        self.history = []
        self.hint_used = False

        self.app.set_input_handler(self._handle_input)
        self.app.ui.set_status(self.app.tr("game.codebreaker.status"))
        self.app.audio.play("success")
        self._render()

    def _handle_input(self, raw: str) -> None:
        guess = raw.strip().lower()
        if not guess:
            self._render(self.app.tr("game.codebreaker.invalid"))
            return

        if guess in {"exit", "salir", "sair", "quit"}:
            self._finish(
                won=False,
                cancelled=True,
                message=self.app.tr("game.codebreaker.cancel"),
            )
            return

        if guess == "hint":
            self._consume_hint()
            return

        if not guess.isdigit() or len(guess) != 4:
            self._render(self.app.tr("game.codebreaker.invalid"))
            return

        if len(set(guess)) != 4:
            self._render(self.app.tr("game.codebreaker.repeat_digit"))
            return

        self.attempts_left -= 1
        exact, near = self._score_guess(guess, self.secret)
        self.history.append(
            self.app.tr(
                "game.codebreaker.feedback",
                guess=guess,
                exact=exact,
                near=near,
            )
        )
        self.app.audio.play("tick")

        if exact == 4:
            self._finish(
                won=True,
                cancelled=False,
                message=self.app.tr("game.codebreaker.win"),
            )
            return

        if self.attempts_left <= 0:
            self._finish(
                won=False,
                cancelled=False,
                message=self.app.tr("game.codebreaker.lose", secret=self.secret),
            )
            return

        self._render()

    def _consume_hint(self) -> None:
        if self.hint_used:
            self._render(self.app.tr("game.codebreaker.hint_once"))
            return

        if self.attempts_left <= 1:
            self._render(self.app.tr("game.codebreaker.hint_no_attempts"))
            return

        self.hint_used = True
        self.attempts_left -= 1
        reveal_idx = random.randint(0, 3)
        reveal_digit = self.secret[reveal_idx]
        self.history.append(
            self.app.tr("game.codebreaker.hint", position=(reveal_idx + 1), digit=reveal_digit)
        )
        self.app.audio.play("success")

        if self.attempts_left <= 0:
            self._finish(
                won=False,
                cancelled=False,
                message=self.app.tr("game.codebreaker.lose", secret=self.secret),
            )
            return

        self._render()

    def _finish(self, won: bool, cancelled: bool, message: str) -> None:
        self.active = False
        self.app.clear_input_handler()
        self.app.ui.set_status(self.app.tr("ui.ready"))

        lines = [
            self.app.tr("game.codebreaker.title"),
            "==========================================",
            "",
            message,
            self.app.tr("game.codebreaker.again"),
        ]
        self.app.ui.set_screen("\n".join(lines))

        if cancelled:
            self.app.audio.play("tick")
            return

        self.app.audio.play("success" if won else "game_over")
        self.app.on_codebreaker_finished(
            won=won,
            attempts_used=(self.max_attempts - self.attempts_left),
            hint_used=self.hint_used,
        )

    def _render(self, message: str = "") -> None:
        lines = [
            self.app.tr("game.codebreaker.title"),
            "==========================================",
            self.app.tr(
                "game.codebreaker.tries",
                left=self.attempts_left,
                total=self.max_attempts,
            ),
            self.app.tr("game.codebreaker.instructions"),
            self.app.tr("game.codebreaker.controls"),
            "",
        ]

        if self.history:
            lines.append(self.app.tr("game.codebreaker.history"))
            lines.extend(f"- {item}" for item in self.history[-8:])
        else:
            lines.append(self.app.tr("game.codebreaker.empty_history"))

        if message:
            lines.extend(["", message])

        self.app.ui.set_screen("\n".join(lines))

    @staticmethod
    def _score_guess(guess: str, secret: str) -> tuple[int, int]:
        exact = sum(1 for i in range(4) if guess[i] == secret[i])
        near = sum(1 for ch in guess if ch in secret) - exact
        return exact, near

    def _attempts_by_graphics(self) -> int:
        attempts_by_graphics = {
            "low": 12,
            "medium": 10,
            "high": 8,
        }
        return attempts_by_graphics.get(self.app.config.graphics, 10)

    @staticmethod
    def _generate_secret() -> str:
        digits = list("0123456789")
        random.shuffle(digits)
        return "".join(digits[:4])


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gethes.app import GethesApp
