from gethes.schema_validation import (
    validate_story_base_payload,
    validate_story_mod_payload,
    validate_theme_payload,
)


def test_validate_theme_payload_accepts_unlock_and_fx() -> None:
    payload = {
        "themes": {
            "neon_grid": {
                "bg": "#06040F",
                "fg": "#CCBEFF",
                "accent": "#8F63FF",
                "fx": {"scan": 1.3, "glow": 1.2, "particles": 1.1},
                "unlock_achievement": "snake_score_120",
            }
        }
    }
    valid, message = validate_theme_payload(payload)
    assert valid is True
    assert message == ""


def test_validate_theme_payload_rejects_invalid_entry() -> None:
    payload = {
        "themes": {
            "broken_theme": {
                "bg": "#000000",
            }
        }
    }
    valid, message = validate_theme_payload(payload)
    assert valid is False
    assert "fg" in message


def test_validate_story_base_payload_rejects_invalid_shape() -> None:
    payload = {
        "title": "Broken",
        "chapters": "not-a-list",
    }
    valid, message = validate_story_base_payload(payload)
    assert valid is False
    assert "chapters" in message


def test_validate_story_mod_payload_accepts_partial_mod() -> None:
    payload = {
        "mode": "append",
        "title": "Delta",
    }
    valid, message = validate_story_mod_payload(payload)
    assert valid is True
    assert message == ""
