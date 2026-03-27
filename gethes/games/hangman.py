from __future__ import annotations

import random
import unicodedata


HANGMAN_STAGES = [
    r"""
 +---+
 |   |
     |
     |
     |
     |
=========""",
    r"""
 +---+
 |   |
 O   |
     |
     |
     |
=========""",
    r"""
 +---+
 |   |
 O   |
 |   |
     |
     |
=========""",
    r"""
 +---+
 |   |
 O   |
/|   |
     |
     |
=========""",
    r"""
 +---+
 |   |
 O   |
/|\  |
     |
     |
=========""",
    r"""
 +---+
 |   |
 O   |
/|\  |
/    |
     |
=========""",
    r"""
 +---+
 |   |
 O   |
/|\  |
/ \  |
     |
=========""",
]


class HangmanGame:
    def __init__(self, app: "GethesApp", words: list[str]) -> None:
        self.app = app
        self.words = words
        self.mode = "1P"
        self.secret_word = ""
        self.secret_normalized = ""
        self.used_letters: set[str] = set()
        self.errors = 0
        self.max_errors = len(HANGMAN_STAGES) - 1
        self.active = False
        self.waiting_secret_word = False
        self.hint_used = False

    def start_single_player(self) -> None:
        word = random.choice(self.words)
        self._start_round(word, mode="1P")

    def start_two_player(self) -> None:
        self.waiting_secret_word = True
        self.active = False
        self.mode = "2P"
        clear_panel_fn = getattr(self.app, "clear_live_leaderboard_panel", None)
        if callable(clear_panel_fn):
            clear_panel_fn()
        self.app.set_input_handler(self._capture_secret_word)
        self.app.ui.set_echo(False)
        self.app.ui.set_input_mask(True)
        self.app.ui.set_status(self.app.tr("game.hangman.setup_status"))
        self.app.ui.set_screen(
            "\n".join(
                [
                    self.app.tr("game.hangman.setup_title"),
                    "==========================================",
                    self.app.tr("game.hangman.setup_hint1"),
                    self.app.tr("game.hangman.setup_hint2"),
                    "",
                    self.app.tr("game.hangman.exit_cmd"),
                ]
            )
        )

    def _capture_secret_word(self, raw: str) -> None:
        candidate = raw.strip()
        if candidate.lower() in {"exit", "salir", "sair", "cancel"}:
            self._abort_setup()
            return

        if not candidate:
            self.app.ui.set_screen(self.app.tr("game.hangman.empty_secret"))
            return

        if not self._is_valid_secret_word(candidate):
            self.app.ui.set_screen(self.app.tr("game.hangman.invalid_secret"))
            return

        self.app.ui.set_echo(True)
        self.app.ui.set_input_mask(False)
        self._start_round(candidate, mode="2P")

    def _abort_setup(self) -> None:
        self.waiting_secret_word = False
        self.app.clear_input_handler()
        self.app.ui.set_echo(True)
        self.app.ui.set_input_mask(False)
        self.app.ui.set_status(self.app.tr("ui.ready"))
        clear_panel_fn = getattr(self.app, "clear_live_leaderboard_panel", None)
        if callable(clear_panel_fn):
            clear_panel_fn()
        self.app.ui.set_screen(self.app.tr("game.hangman.cancelled_setup"))

    def _start_round(self, word: str, mode: str) -> None:
        self.mode = mode
        self.secret_word = word.strip().upper()
        self.secret_normalized = self._normalize_phrase(self.secret_word)
        self.used_letters.clear()
        self.errors = 0
        self.hint_used = False
        self.active = True
        self.waiting_secret_word = False
        self.app.set_input_handler(self._handle_guess)
        self.app.ui.set_status(self.app.tr("game.hangman.active_status"))
        self.app.audio.play("success")
        self._render()

    def _handle_guess(self, raw: str) -> None:
        guess = raw.strip()
        if not guess:
            self._render(self.app.tr("game.hangman.empty_guess"))
            return

        if guess.lower() in {"exit", "salir", "sair", "cancel"}:
            self._finish(
                message=self.app.tr("game.hangman.cancelled_game"),
                won=False,
                cancelled=True,
            )
            return
        if guess.lower() in {"hint", "pista", "dica"}:
            self._use_hint()
            return

        normalized_guess = self._normalize_phrase(guess)

        if len(normalized_guess) == 1 and normalized_guess.isalpha():
            letter = normalized_guess
            if letter in self.used_letters:
                self._render(self.app.tr("game.hangman.letter_used", letter=letter))
                return
            self.used_letters.add(letter)
            if letter in self.secret_normalized:
                self.app.audio.play("success")
            else:
                self.errors += 1
                self.app.audio.play("error")
        else:
            if normalized_guess == self.secret_normalized:
                self._finish(message=self.app.tr("game.hangman.guessed_word"), won=True)
                return
            self.errors += 1
            self.app.audio.play("error")

        if self._is_word_revealed():
            self._finish(message=self.app.tr("game.hangman.completed_word"), won=True)
            return

        if self.errors >= self.max_errors:
            self._finish(message=self.app.tr("game.hangman.no_attempts"), won=False)
            return

        self._render()

    def _use_hint(self) -> None:
        if self.hint_used:
            self._render(self.app.tr("game.hangman.hint_used"))
            return

        candidates = []
        for char in self.secret_word:
            normalized = self._normalize_phrase(char)
            if normalized.isalpha() and normalized not in self.used_letters:
                candidates.append(normalized)

        if not candidates:
            self._render(self.app.tr("game.hangman.hint_used"))
            return

        if self.errors >= self.max_errors - 1:
            self._render(self.app.tr("game.hangman.hint_no_attempts"))
            return

        letter = random.choice(candidates)
        self.used_letters.add(letter)
        self.errors += 1
        self.hint_used = True
        self.app.audio.play("tick")

        if self._is_word_revealed():
            self._finish(message=self.app.tr("game.hangman.completed_word"), won=True)
            return

        if self.errors >= self.max_errors:
            self._finish(message=self.app.tr("game.hangman.no_attempts"), won=False)
            return

        self._render(self.app.tr("game.hangman.hint_reveal", letter=letter))

    def _is_word_revealed(self) -> bool:
        for char in self.secret_word:
            nchar = self._normalize_phrase(char)
            if nchar.isalpha() and nchar not in self.used_letters:
                return False
        return True

    def _masked_word(self, reveal: bool = False) -> str:
        chars: list[str] = []
        for char in self.secret_word:
            normalized = self._normalize_phrase(char)
            if normalized.isalpha():
                if reveal or normalized in self.used_letters:
                    chars.append(char)
                else:
                    chars.append("_")
            else:
                chars.append(char)
        return " ".join(chars)

    def _render(self, message: str = "") -> None:
        used = ", ".join(sorted(self.used_letters)) or "-"
        remaining = self.max_errors - self.errors
        lines = [
            self.app.tr("game.hangman.title", mode=self.mode),
            "==========================================",
            HANGMAN_STAGES[self.errors],
            "",
            self.app.tr("game.hangman.word", word=self._masked_word()),
            self.app.tr("game.hangman.used", letters=used),
            self.app.tr("game.hangman.left", count=remaining),
            "",
            self.app.tr("game.hangman.commands"),
        ]
        if message:
            lines.extend(["", message])
        self.app.ui.set_screen("\n".join(lines))
        panel_fn = getattr(self.app, "set_live_leaderboard_panel", None)
        if callable(panel_fn):
            panel_fn(
                "hangman",
                current_lines=[
                    self.app.tr("game.hangman.title", mode=self.mode),
                    self.app.tr("game.hangman.left", count=max(0, self.max_errors - self.errors)),
                ],
            )

    def _finish(self, message: str, won: bool, cancelled: bool = False) -> None:
        self.active = False
        self.waiting_secret_word = False
        self.app.clear_input_handler()
        self.app.ui.set_echo(True)
        self.app.ui.set_input_mask(False)
        self.app.ui.set_status(self.app.tr("ui.ready"))

        if not cancelled:
            result = self.app.tr("game.hangman.win") if won else self.app.tr("game.hangman.lose")
            lines = [
                f"{self.app.tr('game.hangman.title', mode=self.mode)} | {result}",
                "==========================================",
                HANGMAN_STAGES[self.errors],
                "",
                self.app.tr("game.hangman.word", word=self._masked_word(reveal=True)),
                self.app.tr("game.hangman.left", count=max(0, self.max_errors - self.errors)),
                "",
                message,
                self.app.tr("game.hangman.again"),
            ]
            self.app.ui.set_screen("\n".join(lines))
            clear_panel_fn = getattr(self.app, "clear_live_leaderboard_panel", None)
            if callable(clear_panel_fn):
                clear_panel_fn()
            self.app.audio.play("success" if won else "game_over")
            self.app.on_hangman_finished(
                won=won,
                mode=self.mode,
                errors=self.errors,
                hint_used=self.hint_used,
            )
            return

        self.app.ui.set_screen(f"{message}\n{self.app.tr('generic.exit_help')}")
        clear_panel_fn = getattr(self.app, "clear_live_leaderboard_panel", None)
        if callable(clear_panel_fn):
            clear_panel_fn()

    @staticmethod
    def _is_valid_secret_word(value: str) -> bool:
        for char in value:
            if char in {" ", "-"}:
                continue
            if not char.isalpha():
                return False
        return True

    @staticmethod
    def _normalize_phrase(value: str) -> str:
        marker = "__ENYE__"
        upper = value.upper().replace("\u00D1", marker)
        decomposed = unicodedata.normalize("NFD", upper)
        stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
        normalized = stripped.replace(marker, "\u00D1")
        return " ".join(normalized.split())


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gethes.app import GethesApp
