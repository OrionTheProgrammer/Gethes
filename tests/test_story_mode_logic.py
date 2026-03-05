import json
from pathlib import Path
from types import SimpleNamespace

from gethes.story.story_mode import StoryMode


class _DummyApp:
    def __init__(self) -> None:
        self.i18n = SimpleNamespace(active_language="es")

    def tr(self, key: str, **_kwargs: object) -> str:
        return key


def _write_story(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_story_append_mode_merges_chapters(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    mod_dir = tmp_path / "mods"
    base_dir.mkdir()
    mod_dir.mkdir()

    base = {
        "title": "Base",
        "chapters": [{"title": "A", "pages": ["p1"]}],
    }
    mod = {
        "mode": "append",
        "title": "Base+",
        "chapters": [{"title": "B", "pages": ["p2"]}],
    }
    _write_story(base_dir / "story_es.json", base)
    _write_story(mod_dir / "story.json", mod)

    story = StoryMode(_DummyApp(), base_dir, mod_story_dir=mod_dir)
    assert story.story_title == "Base+"
    assert len(story.pages) == 2


def test_story_replace_mode_overrides_base(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    mod_dir = tmp_path / "mods"
    base_dir.mkdir()
    mod_dir.mkdir()

    base = {
        "title": "Base",
        "chapters": [{"title": "A", "pages": ["p1"]}],
    }
    mod = {
        "mode": "replace",
        "title": "Only Mod",
        "chapters": [{"title": "X", "pages": ["m1", "m2"]}],
    }
    _write_story(base_dir / "story_es.json", base)
    _write_story(mod_dir / "story.json", mod)

    story = StoryMode(_DummyApp(), base_dir, mod_story_dir=mod_dir)
    assert story.story_title == "Only Mod"
    assert len(story.pages) == 2
