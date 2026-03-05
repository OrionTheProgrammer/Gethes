from gethes.games.hangman import HangmanGame


def test_is_valid_secret_word() -> None:
    assert HangmanGame._is_valid_secret_word("hola mundo")
    assert HangmanGame._is_valid_secret_word("data-core")
    assert not HangmanGame._is_valid_secret_word("clave123")


def test_normalize_phrase_keeps_enye_and_strips_accents() -> None:
    value = HangmanGame._normalize_phrase("Canción niño")
    assert value == "CANCION NIÑO"
