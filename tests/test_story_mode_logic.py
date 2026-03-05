import json
from pathlib import Path
from types import SimpleNamespace

from gethes.story.story_mode import StoryMode


class _DummyApp:
    def __init__(self) -> None:
        self.i18n = SimpleNamespace(active_language="es")

    def tr(self, key: str, **_kwargs: object) -> str:
        return key


class _DummyUI:
    def __init__(self) -> None:
        self.last_screen = ""
        self.status = ""
        self.notifications: list[tuple[str, str]] = []

    def set_status(self, value: str) -> None:
        self.status = value

    def set_screen(self, content: str) -> None:
        self.last_screen = content

    def push_notification(self, title: str, message: str, icon_key: str = "") -> None:
        self.notifications.append((title, message))

    def trigger_glitch(self, duration: float = 0.0) -> None:
        _ = duration


class _DummyAudio:
    def __init__(self) -> None:
        self.played: list[str] = []

    def play(self, event: str) -> None:
        self.played.append(event)


class _DummyRuntimeApp(_DummyApp):
    def __init__(self) -> None:
        super().__init__()
        self.ui = _DummyUI()
        self.audio = _DummyAudio()
        self.current_slot = SimpleNamespace(
            story_page=0,
            story_total=0,
            story_title="",
            flags={},
            stats={},
        )
        self.input_handler = None
        self.story_completed = None
        self.choice_events: list[str] = []
        self.secret_unlocked: list[str] = []
        self.secret_viewed: list[str] = []
        self.route_events: list[str] = []

    def set_input_handler(self, handler) -> None:  # type: ignore[no-untyped-def]
        self.input_handler = handler

    def clear_input_handler(self) -> None:
        self.input_handler = None

    def on_story_progress(self, page: int, total: int, title: str) -> None:
        self.current_slot.story_page = page
        self.current_slot.story_total = total
        self.current_slot.story_title = title

    def on_story_finished(self, completed: bool) -> None:
        self.story_completed = completed

    def on_story_choice_made(self, choice_flag: str) -> None:
        self.choice_events.append(choice_flag)

    def on_story_secret_unlocked(self, secret_id: str) -> None:
        self.current_slot.flags[f"story_secret_unlocked_{secret_id}"] = True
        self.secret_unlocked.append(secret_id)

    def on_story_secret_viewed(self, secret_id: str) -> None:
        self.secret_viewed.append(secret_id)

    def on_story_route_entered(self, route_id: str) -> None:
        self.route_events.append(route_id)


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


def test_story_supports_choices_and_secret_files(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    base_dir.mkdir()

    payload = {
        "title": "Branching Story",
        "secrets": [
            {"id": "memo_alpha", "title": "Memo Alpha", "content": "test secret"},
        ],
        "chapters": [
            {
                "title": "Start",
                "pages": [
                    {
                        "id": "node_start",
                        "text": "start text",
                        "choices": [
                            {
                                "label": "Take route A",
                                "target": "node_a",
                                "flag": "story_choice_a",
                            }
                        ],
                        "unlocks": ["memo_alpha"],
                    },
                    {"id": "node_a", "text": "route a"},
                ],
            }
        ],
    }
    _write_story(base_dir / "story_es.json", payload)

    story = StoryMode(_DummyApp(), base_dir)
    assert story.story_title == "Branching Story"
    assert len(story.pages) == 2
    assert story.pages[0]["id"] == "node_start"
    assert isinstance(story.pages[0]["choices"], list)
    assert story.pages[0]["choices"][0]["flag"] == "story_choice_a"
    assert "memo_alpha" in story.secret_files


def test_story_runtime_handles_choices_and_secret_open(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    base_dir.mkdir()

    payload = {
        "title": "Runtime Story",
        "secrets": [
            {"id": "memo_alpha", "title": "Memo Alpha", "content": "secret body"},
        ],
        "chapters": [
            {
                "title": "Entry",
                "pages": [
                    {
                        "id": "node_start",
                        "text": "start",
                        "unlocks": ["memo_alpha"],
                        "choices": [
                            {
                                "label": "Go route A",
                                "target": "node_route_a",
                                "flag": "story_choice_a",
                            }
                        ],
                    },
                    {
                        "id": "node_route_a",
                        "text": "route A",
                        "route": "companion",
                    },
                ],
            }
        ],
    }
    _write_story(base_dir / "story_es.json", payload)

    app = _DummyRuntimeApp()
    story = StoryMode(app, base_dir)
    story.start()

    assert app.input_handler is not None
    assert "memo_alpha" in app.secret_unlocked

    story._handle_input("1")
    assert "story_choice_a" in app.choice_events
    assert "companion" in app.route_events

    story._handle_input("open memo_alpha")
    assert "memo_alpha" in app.secret_viewed
