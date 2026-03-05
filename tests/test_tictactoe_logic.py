from gethes.games.tictactoe import TicTacToeGame


class _DummyAudio:
    def play(self, _event: str) -> None:
        return


class _DummyApp:
    def __init__(self) -> None:
        self.audio = _DummyAudio()


def test_winner_line_detection() -> None:
    game = TicTacToeGame(_DummyApp())
    game.board = ["X", "X", "X", "4", "5", "6", "7", "8", "9"]
    assert game._winner_line("X") == (0, 1, 2)
    assert game._winner_line("O") is None


def test_cpu_uses_immediate_winning_move() -> None:
    game = TicTacToeGame(_DummyApp())
    game.board = ["O", "O", "3", "X", "X", "6", "7", "8", "9"]
    game._cpu_move()
    assert game.board[2] == "O"
