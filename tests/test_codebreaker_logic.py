from types import SimpleNamespace

from gethes.games.codebreaker import CodeBreakerGame


class _DummyApp:
    def __init__(self, graphics: str) -> None:
        self.config = SimpleNamespace(graphics=graphics)


def test_score_guess_exact_and_near() -> None:
    exact, near = CodeBreakerGame._score_guess("1234", "1243")
    assert exact == 2
    assert near == 2


def test_generate_secret_is_four_unique_digits() -> None:
    secret = CodeBreakerGame._generate_secret()
    assert len(secret) == 4
    assert secret.isdigit()
    assert len(set(secret)) == 4


def test_attempts_vary_by_graphics() -> None:
    low = CodeBreakerGame(_DummyApp("low"))._attempts_by_graphics()
    medium = CodeBreakerGame(_DummyApp("medium"))._attempts_by_graphics()
    high = CodeBreakerGame(_DummyApp("high"))._attempts_by_graphics()

    assert low > medium > high
