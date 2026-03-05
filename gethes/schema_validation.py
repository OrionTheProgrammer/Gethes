from __future__ import annotations

from typing import Iterable

from jsonschema import Draft202012Validator, ValidationError


_STRENGTH_RULE = {"type": "number", "minimum": 0.2, "maximum": 2.0}

_THEME_ENTRY_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["bg", "fg"],
    "properties": {
        "bg": {"type": "string", "minLength": 1},
        "fg": {"type": "string", "minLength": 1},
        "accent": {"type": "string"},
        "panel": {"type": "string"},
        "dim": {"type": "string"},
        "unlock_achievement": {"type": "string"},
        "scan_strength": _STRENGTH_RULE,
        "glow_strength": _STRENGTH_RULE,
        "particle_strength": _STRENGTH_RULE,
        "scan": _STRENGTH_RULE,
        "glow": _STRENGTH_RULE,
        "particles": _STRENGTH_RULE,
        "fx": {
            "type": "object",
            "properties": {
                "scan": _STRENGTH_RULE,
                "glow": _STRENGTH_RULE,
                "particles": _STRENGTH_RULE,
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": True,
}

_THEME_SINGLE_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["name", "bg", "fg"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        **_THEME_ENTRY_SCHEMA["properties"],  # type: ignore[index]
    },
    "additionalProperties": True,
}

_THEME_ENTRY_VALIDATOR = Draft202012Validator(_THEME_ENTRY_SCHEMA)
_THEME_SINGLE_VALIDATOR = Draft202012Validator(_THEME_SINGLE_SCHEMA)

_STORY_PAGE_OBJECT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "text": {"type": "string"},
        "body": {"type": "string"},
        "mood": {"type": "string"},
        "next": {"type": "string"},
        "route": {"type": "string"},
        "fx": {"type": "string"},
        "unlocks": {"type": "array", "items": {"type": "string"}},
        "choices": {
            "type": "array",
            "items": {
                "oneOf": [
                    {"type": "string"},
                    {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "text": {"type": "string"},
                            "target": {"type": "string"},
                            "flag": {"type": "string"},
                        },
                        "additionalProperties": True,
                    },
                ]
            },
        },
    },
    "additionalProperties": True,
}

_STORY_CHAPTER_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["pages"],
    "properties": {
        "title": {"type": "string"},
        "pages": {
            "type": "array",
            "items": {
                "oneOf": [
                    {"type": "string"},
                    _STORY_PAGE_OBJECT_SCHEMA,
                ]
            },
        },
    },
    "additionalProperties": True,
}

_STORY_SECRET_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "content": {"type": "string"},
        "text": {"type": "string"},
        "requires": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}

_STORY_BASE_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["chapters"],
    "properties": {
        "title": {"type": "string"},
        "mode": {"type": "string"},
        "chapters": {"type": "array", "items": _STORY_CHAPTER_SCHEMA},
        "secrets": {"type": "array", "items": _STORY_SECRET_SCHEMA},
    },
    "additionalProperties": True,
}

_STORY_MOD_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "mode": {"type": "string"},
        "chapters": {"type": "array", "items": _STORY_CHAPTER_SCHEMA},
        "secrets": {"type": "array", "items": _STORY_SECRET_SCHEMA},
    },
    "additionalProperties": True,
}

_STORY_BASE_VALIDATOR = Draft202012Validator(_STORY_BASE_SCHEMA)
_STORY_MOD_VALIDATOR = Draft202012Validator(_STORY_MOD_SCHEMA)


def _first_error(errors: Iterable[ValidationError]) -> str:
    first = next(iter(errors), None)
    if first is None:
        return ""
    path = ".".join(str(part) for part in first.absolute_path)
    if path:
        return f"{path}: {first.message}"
    return str(first.message)


def validate_theme_payload(payload: object) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "theme payload must be an object"

    seen_theme_entries = False

    has_single = all(isinstance(payload.get(key), str) for key in ("name", "bg", "fg"))
    if has_single:
        errors = _THEME_SINGLE_VALIDATOR.iter_errors(payload)
        message = _first_error(errors)
        if message:
            return False, message
        seen_theme_entries = True

    theme_pack = payload.get("themes")
    if theme_pack is not None:
        if not isinstance(theme_pack, dict):
            return False, "`themes` must be an object"
        for name, item in theme_pack.items():
            if not isinstance(name, str):
                return False, "theme name in `themes` must be a string"
            if not isinstance(item, dict):
                return False, f"`themes.{name}` must be an object"
            message = _first_error(_THEME_ENTRY_VALIDATOR.iter_errors(item))
            if message:
                return False, f"`themes.{name}` {message}"
            seen_theme_entries = True

    for name, item in payload.items():
        if name in {"themes", "name", "bg", "fg", "accent", "panel", "dim"}:
            continue
        if not isinstance(name, str) or not isinstance(item, dict):
            continue
        if "bg" not in item and "fg" not in item:
            continue
        message = _first_error(_THEME_ENTRY_VALIDATOR.iter_errors(item))
        if message:
            return False, f"`{name}` {message}"
        seen_theme_entries = True

    if not seen_theme_entries:
        return False, "no valid theme entries found"
    return True, ""


def validate_story_base_payload(payload: object) -> tuple[bool, str]:
    errors = _STORY_BASE_VALIDATOR.iter_errors(payload)
    message = _first_error(errors)
    if message:
        return False, message
    return True, ""


def validate_story_mod_payload(payload: object) -> tuple[bool, str]:
    errors = _STORY_MOD_VALIDATOR.iter_errors(payload)
    message = _first_error(errors)
    if message:
        return False, message
    return True, ""
