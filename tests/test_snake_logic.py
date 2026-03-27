from gethes.games.snake import SnakeGame


def test_snake_mode_aliases_online() -> None:
    assert SnakeGame._normalize_mode("online") == "online"
    assert SnakeGame._normalize_mode("slither") == "online"
    assert SnakeGame._normalize_mode("agario") == "online"


def test_snake_mode_aliases_multiapple() -> None:
    assert SnakeGame._normalize_mode("multiapple") == "multiapple"
    assert SnakeGame._normalize_mode("multimanzana") == "multiapple"


def test_snake_difficulty_aliases() -> None:
    assert SnakeGame._normalize_difficulty("normal") == "normal"
    assert SnakeGame._normalize_difficulty("hard") == "hard"
    assert SnakeGame._normalize_difficulty("impossible") == "insane"
    assert SnakeGame._normalize_difficulty("nightmare") == "insane"
