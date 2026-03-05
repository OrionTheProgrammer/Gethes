import pytest

pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st

from gethes.games.codebreaker import CodeBreakerGame


digit_code = st.lists(
    st.sampled_from(list("0123456789")),
    min_size=4,
    max_size=4,
    unique=True,
).map("".join)


@given(secret=digit_code, guess=digit_code)
def test_score_guess_invariants(secret: str, guess: str) -> None:
    exact, near = CodeBreakerGame._score_guess(guess, secret)
    overlap = len(set(guess) & set(secret))

    assert 0 <= exact <= 4
    assert 0 <= near <= 4
    assert exact + near == overlap


@given(secret=digit_code)
def test_score_guess_exact_match(secret: str) -> None:
    exact, near = CodeBreakerGame._score_guess(secret, secret)
    assert (exact, near) == (4, 0)


@given(secret=digit_code, guess=digit_code)
def test_score_guess_is_symmetric(secret: str, guess: str) -> None:
    left = CodeBreakerGame._score_guess(guess, secret)
    right = CodeBreakerGame._score_guess(secret, guess)
    assert left == right
