from __future__ import annotations

import json
from pathlib import Path


class StoryMode:
    def __init__(
        self,
        app: "GethesApp",
        story_dir: Path,
        mod_story_dir: Path | None = None,
    ) -> None:
        self.app = app
        self.story_dir = story_dir
        self.mod_story_dir = mod_story_dir
        self.story_title = "Gethes"
        self.pages: list[dict[str, str | int]] = []
        self.active = False
        self.page_index = 0
        self._load_story()

    def reload_for_language(self) -> None:
        self._load_story()

    def _story_file(self) -> Path:
        code = self.app.i18n.active_language
        preferred = self.story_dir / f"story_{code}.json"
        if preferred.exists():
            return preferred
        return self.story_dir / "story_es.json"

    def _mod_story_file(self) -> Path | None:
        if self.mod_story_dir is None:
            return None
        code = self.app.i18n.active_language
        preferred = self.mod_story_dir / f"story_{code}.json"
        if preferred.exists():
            return preferred
        shared = self.mod_story_dir / "story.json"
        if shared.exists():
            return shared
        return None

    def _load_story(self) -> None:
        story_file = self._story_file()
        fallback = [
            {
                "chapter": self.app.tr("game.story.chapter_default"),
                "chapter_page": 1,
                "text": self.app.tr("game.story.fallback"),
            }
        ]

        try:
            base_data = json.loads(story_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.pages = fallback
            return

        data = base_data if isinstance(base_data, dict) else {}
        mod_file = self._mod_story_file()
        if mod_file is not None:
            try:
                raw_mod = json.loads(mod_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw_mod = None
            if isinstance(raw_mod, dict):
                data = self._merge_story_data(data, raw_mod)

        self.story_title = str(data.get("title", "Gethes"))
        pages: list[dict[str, str | int]] = []
        chapters = data.get("chapters", [])
        if not isinstance(chapters, list):
            self.pages = fallback
            return

        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            chapter_title = str(chapter.get("title", self.app.tr("game.story.chapter_default")))
            chapter_pages = chapter.get("pages", [])
            if not isinstance(chapter_pages, list):
                continue
            for index, text in enumerate(chapter_pages, start=1):
                pages.append(
                    {
                        "chapter": chapter_title,
                        "chapter_page": index,
                        "text": str(text),
                    }
                )

        self.pages = pages or fallback

    def _merge_story_data(
        self,
        base_data: dict[str, object],
        mod_data: dict[str, object],
    ) -> dict[str, object]:
        mode = str(mod_data.get("mode", "append")).strip().lower()
        if mode == "replace":
            return mod_data

        merged_title = str(mod_data.get("title", base_data.get("title", "Gethes")))
        merged_chapters: list[object] = []
        if isinstance(base_data.get("chapters"), list):
            merged_chapters.extend(base_data["chapters"])
        if isinstance(mod_data.get("chapters"), list):
            merged_chapters.extend(mod_data["chapters"])

        return {"title": merged_title, "chapters": merged_chapters}

    def start(self) -> None:
        self.active = True
        self._load_story()
        total_pages = len(self.pages)
        saved_page = self.app.current_slot.story_page
        if saved_page <= 1 or saved_page >= total_pages:
            self.page_index = 0
        else:
            self.page_index = min(max(0, saved_page - 1), max(0, total_pages - 1))
        self.app.set_input_handler(self._handle_input)
        self.app.audio.play("success")
        self.app.ui.set_status(self.app.tr("game.story.status"))
        self._render_page()

    def _handle_input(self, raw: str) -> None:
        command = raw.strip().lower()
        if command in {"exit", "salir", "sair"}:
            self._finish(completed=False)
            return

        if command in {"prev", "anterior", "p"}:
            if self.page_index == 0:
                self._render_page(self.app.tr("game.story.first_page"))
                return
            self.page_index -= 1
            self._render_page()
            return

        if command in {"", "next", "siguiente", "seguinte", "n"}:
            if self.page_index >= len(self.pages) - 1:
                self._finish(completed=True)
                return
            self.page_index += 1
            self.app.audio.play("tick")
            self._render_page()
            return

        self._render_page(self.app.tr("game.story.invalid"))

    def _render_page(self, message: str = "") -> None:
        page = self.pages[self.page_index]
        title = self.app.tr("game.story.title", title=self.story_title)
        chapter = str(page["chapter"])
        chapter_page = int(page["chapter_page"])
        text = str(page["text"])
        total = len(self.pages)
        current = self.page_index + 1

        lines = [
            title,
            "==========================================",
            self.app.tr("game.story.chapter_page", chapter=chapter, page=chapter_page),
            self.app.tr("game.story.mood_line"),
            "",
            text,
            "",
            self.app.tr("game.story.controls", current=current, total=total),
        ]
        if message:
            lines.extend(["", message])
        self.app.ui.set_screen("\n".join(lines))
        self.app.audio.play("message")
        self.app.on_story_progress(
            page=self.page_index + 1,
            total=len(self.pages),
            title=self.story_title,
        )

    def _finish(self, completed: bool) -> None:
        self.active = False
        self.app.clear_input_handler()
        self.app.ui.set_status(self.app.tr("ui.ready"))
        self.app.on_story_finished(completed=completed)
        if completed:
            self.app.audio.play("success")
            self.app.ui.set_screen(self.app.tr("game.story.finish"))
            return

        self.app.ui.set_screen(self.app.tr("game.story.close"))


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gethes.app import GethesApp
