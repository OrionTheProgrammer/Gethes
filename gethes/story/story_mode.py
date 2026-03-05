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
        self.pages: list[dict[str, object]] = []
        self.page_by_id: dict[str, int] = {}
        self.secret_files: dict[str, dict[str, object]] = {}
        self.secret_unlocked_ids: set[str] = set()
        self.active = False
        self.page_index = 0
        self.page_history: list[int] = []
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

    def _normalize_id(self, value: str, fallback: str) -> str:
        raw = value.strip().lower()
        if not raw:
            return fallback
        chars: list[str] = []
        prev_is_sep = False
        for ch in raw:
            if ch.isalnum():
                chars.append(ch)
                prev_is_sep = False
                continue
            if not prev_is_sep:
                chars.append("_")
            prev_is_sep = True
        normalized = "".join(chars).strip("_")
        return normalized or fallback

    def _normalize_secret_files(self, payload: object) -> dict[str, dict[str, object]]:
        if not isinstance(payload, list):
            return {}

        files: dict[str, dict[str, object]] = {}
        for idx, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                continue
            file_id = self._normalize_id(str(item.get("id", "")), f"secret_{idx}")
            title = str(item.get("title", f"Secret {idx}")).strip() or f"Secret {idx}"
            content = str(item.get("content", item.get("text", ""))).strip()
            if not content:
                continue
            requires: list[str] = []
            raw_requires = item.get("requires", [])
            if isinstance(raw_requires, list):
                for raw_flag in raw_requires:
                    if not isinstance(raw_flag, str):
                        continue
                    flag = raw_flag.strip()
                    if flag:
                        requires.append(flag)
            files[file_id] = {
                "id": file_id,
                "title": title,
                "content": content,
                "requires": requires,
            }
        return files

    def _normalize_unlocks(self, payload: object) -> list[str]:
        if not isinstance(payload, list):
            return []
        items: list[str] = []
        for raw in payload:
            if not isinstance(raw, str):
                continue
            token = self._normalize_id(raw, "")
            if token:
                items.append(token)
        return items

    def _normalize_choices(self, payload: object, page_id: str) -> list[dict[str, str]]:
        if not isinstance(payload, list):
            return []

        choices: list[dict[str, str]] = []
        for idx, item in enumerate(payload, start=1):
            if isinstance(item, dict):
                label = str(item.get("label", item.get("text", ""))).strip()
                target = self._normalize_id(str(item.get("target", "")), "")
                flag = str(item.get("flag", "")).strip()
            else:
                label = str(item).strip()
                target = ""
                flag = ""

            if not label:
                continue
            if not flag:
                flag = f"story_choice_{page_id}_{idx}"
            choices.append(
                {
                    "label": label,
                    "target": target,
                    "flag": flag,
                }
            )
        return choices

    def _load_story(self) -> None:
        story_file = self._story_file()
        fallback = [
            {
                "id": "fallback_1",
                "chapter": self.app.tr("game.story.chapter_default"),
                "chapter_page": 1,
                "text": self.app.tr("game.story.fallback"),
                "mood": "",
                "next": "",
                "choices": [],
                "unlocks": [],
                "route": "",
                "fx": "",
            }
        ]

        try:
            base_data = json.loads(story_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.pages = fallback
            self.page_by_id = {"fallback_1": 0}
            self.secret_files = {}
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
        self.secret_files = self._normalize_secret_files(data.get("secrets", []))

        pages: list[dict[str, object]] = []
        used_ids: set[str] = set()
        chapters = data.get("chapters", [])
        if not isinstance(chapters, list):
            self.pages = fallback
            self.page_by_id = {"fallback_1": 0}
            return

        for chapter_index, chapter in enumerate(chapters, start=1):
            if not isinstance(chapter, dict):
                continue
            chapter_title = str(chapter.get("title", self.app.tr("game.story.chapter_default")))
            chapter_pages = chapter.get("pages", [])
            if not isinstance(chapter_pages, list):
                continue

            for page_index, raw_page in enumerate(chapter_pages, start=1):
                default_page_id = f"ch{chapter_index}_p{page_index}"
                if isinstance(raw_page, str):
                    page_id = default_page_id
                    page_text = raw_page
                    mood = ""
                    next_target = ""
                    choices: list[dict[str, str]] = []
                    unlocks: list[str] = []
                    route = ""
                    fx = ""
                elif isinstance(raw_page, dict):
                    page_id = self._normalize_id(str(raw_page.get("id", "")), default_page_id)
                    page_text = str(raw_page.get("text", raw_page.get("body", ""))).strip()
                    if not page_text:
                        continue
                    mood = str(raw_page.get("mood", "")).strip()
                    next_target = self._normalize_id(str(raw_page.get("next", "")), "")
                    choices = self._normalize_choices(raw_page.get("choices", []), page_id)
                    unlocks = self._normalize_unlocks(raw_page.get("unlocks", []))
                    route = self._normalize_id(str(raw_page.get("route", "")), "")
                    fx = str(raw_page.get("fx", "")).strip().lower()
                else:
                    continue

                unique_id = page_id
                if unique_id in used_ids:
                    suffix = 2
                    while f"{page_id}_{suffix}" in used_ids:
                        suffix += 1
                    unique_id = f"{page_id}_{suffix}"
                used_ids.add(unique_id)

                pages.append(
                    {
                        "id": unique_id,
                        "chapter": chapter_title,
                        "chapter_page": page_index,
                        "text": page_text,
                        "mood": mood,
                        "next": next_target,
                        "choices": choices,
                        "unlocks": unlocks,
                        "route": route,
                        "fx": fx,
                    }
                )

        self.pages = pages or fallback
        self.page_by_id = {}
        for index, page in enumerate(self.pages):
            page_id = str(page.get("id", "")).strip()
            if page_id:
                self.page_by_id[page_id] = index

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

        merged_secrets: list[object] = []
        if isinstance(base_data.get("secrets"), list):
            merged_secrets.extend(base_data["secrets"])
        if isinstance(mod_data.get("secrets"), list):
            merged_secrets.extend(mod_data["secrets"])

        return {
            "title": merged_title,
            "chapters": merged_chapters,
            "secrets": merged_secrets,
        }

    def start(self) -> None:
        self.active = True
        self._load_story()
        self.page_history = []
        total_pages = len(self.pages)
        saved_page = self.app.current_slot.story_page
        if saved_page <= 1 or saved_page >= total_pages:
            self.page_index = 0
        else:
            self.page_index = min(max(0, saved_page - 1), max(0, total_pages - 1))

        self.secret_unlocked_ids = set()
        for secret_id in self.secret_files:
            key = f"story_secret_unlocked_{secret_id}"
            if self.app.current_slot.flags.get(key, False):
                self.secret_unlocked_ids.add(secret_id)

        self.app.set_input_handler(self._handle_input)
        self.app.audio.play("success")
        self.app.ui.set_status(self.app.tr("game.story.status"))
        self._render_page()

    def _is_secret_available(self, secret_id: str) -> bool:
        if secret_id not in self.secret_unlocked_ids:
            return False
        secret = self.secret_files.get(secret_id)
        if secret is None:
            return False
        requires = secret.get("requires", [])
        if not isinstance(requires, list):
            return True
        for flag in requires:
            if not isinstance(flag, str):
                continue
            if not self.app.current_slot.flags.get(flag, False):
                return False
        return True

    def _unlock_page_secrets(self, page: dict[str, object]) -> list[str]:
        raw_unlocks = page.get("unlocks", [])
        if not isinstance(raw_unlocks, list):
            return []

        unlocked_messages: list[str] = []
        for raw_id in raw_unlocks:
            if not isinstance(raw_id, str):
                continue
            secret_id = self._normalize_id(raw_id, "")
            if not secret_id or secret_id in self.secret_unlocked_ids:
                continue
            secret = self.secret_files.get(secret_id)
            if secret is None:
                continue

            self.secret_unlocked_ids.add(secret_id)
            self.app.on_story_secret_unlocked(secret_id)

            title = str(secret.get("title", secret_id))
            self.app.ui.push_notification(
                self.app.tr("game.story.secret_toast_title"),
                title,
                icon_key="mdi:information-outline",
            )
            self.app.audio.play("secret")
            unlocked_messages.append(
                self.app.tr("game.story.secret_unlock", title=title, id=secret_id)
            )
        return unlocked_messages

    def _current_page_choices(self) -> list[dict[str, str]]:
        page = self.pages[self.page_index]
        raw_choices = page.get("choices", [])
        if not isinstance(raw_choices, list):
            return []
        choices: list[dict[str, str]] = []
        for item in raw_choices:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            flag = str(item.get("flag", "")).strip()
            target = str(item.get("target", "")).strip()
            if not label or not flag:
                continue
            choices.append({"label": label, "flag": flag, "target": target})
        return choices

    def _selected_choice(self, choices: list[dict[str, str]]) -> dict[str, str] | None:
        for choice in choices:
            if self.app.current_slot.flags.get(choice["flag"], False):
                return choice
        return None

    def _set_choice(self, choices: list[dict[str, str]], selected: dict[str, str]) -> None:
        changed = False
        for choice in choices:
            key = choice["flag"]
            selected_value = choice["flag"] == selected["flag"]
            if self.app.current_slot.flags.get(key, False) != selected_value:
                self.app.current_slot.flags[key] = selected_value
                changed = True
        if changed:
            self.app.on_story_choice_made(selected["flag"])

    def _resolve_target_index(self, target: str) -> int | None:
        token = self._normalize_id(target, "")
        if token:
            found = self.page_by_id.get(token)
            if found is not None:
                return found
        next_index = self.page_index + 1
        if next_index < len(self.pages):
            return next_index
        return None

    def _show_secret_files(self) -> None:
        available: list[tuple[str, str]] = []
        for secret_id, secret in sorted(self.secret_files.items()):
            if not self._is_secret_available(secret_id):
                continue
            title = str(secret.get("title", secret_id))
            available.append((secret_id, title))

        if not available:
            self._render_page(self.app.tr("game.story.files_none"))
            return

        lines = [self.app.tr("game.story.files_title")]
        for secret_id, title in available:
            lines.append(self.app.tr("game.story.files_item", id=secret_id, title=title))
        lines.append(self.app.tr("game.story.files_hint"))
        self._render_page("\n".join(lines))

    def _open_secret_file(self, secret_id_raw: str) -> None:
        secret_id = self._normalize_id(secret_id_raw, "")
        if not secret_id:
            self._render_page(self.app.tr("game.story.open_usage"))
            return
        if not self._is_secret_available(secret_id):
            self._render_page(self.app.tr("game.story.open_missing", id=secret_id))
            return

        secret = self.secret_files[secret_id]
        title = str(secret.get("title", secret_id))
        content = str(secret.get("content", ""))
        self.app.on_story_secret_viewed(secret_id)
        self.app.audio.play("secret")

        message = "\n".join(
            [
                self.app.tr("game.story.open_header", title=title, id=secret_id),
                "------------------------------------------",
                content,
            ]
        )
        self._render_page(message)

    def _advance_to(self, target_index: int, message: str = "") -> None:
        if target_index < 0 or target_index >= len(self.pages):
            self._finish(completed=True)
            return
        if target_index != self.page_index:
            self.page_history.append(self.page_index)
            self.page_index = target_index
            self.app.audio.play("tick")
        self._render_page(message)

    def _handle_input(self, raw: str) -> None:
        command = raw.strip()
        token = command.lower()

        if token in {"exit", "salir", "sair"}:
            self._finish(completed=False)
            return

        if token in {"prev", "anterior", "p"}:
            if self.page_history:
                self.page_index = self.page_history.pop()
                self._render_page()
                return
            if self.page_index == 0:
                self._render_page(self.app.tr("game.story.first_page"))
                return
            self.page_index -= 1
            self._render_page()
            return

        if token in {"files", "archivos", "arquivos", "secret", "secrets"}:
            self._show_secret_files()
            return

        if token in {"open", "archivo", "arquivo"}:
            self._render_page(self.app.tr("game.story.open_usage"))
            return
        if token.startswith("open ") or token.startswith("archivo ") or token.startswith("arquivo "):
            _, _, payload = command.partition(" ")
            self._open_secret_file(payload)
            return

        choices = self._current_page_choices()
        if choices and token.isdigit():
            option = int(token)
            if option <= 0 or option > len(choices):
                self._render_page(self.app.tr("game.story.choice_invalid", count=len(choices)))
                return
            selected = choices[option - 1]
            self._set_choice(choices, selected)
            target_index = self._resolve_target_index(selected.get("target", ""))
            if target_index is None:
                self._finish(completed=True)
                return
            self._advance_to(
                target_index,
                message=self.app.tr("game.story.choice_selected", label=selected["label"]),
            )
            return

        if token in {"", "next", "siguiente", "seguinte", "n"}:
            if choices:
                selected = self._selected_choice(choices)
                if selected is None:
                    self._render_page(self.app.tr("game.story.choice_required", count=len(choices)))
                    return
                target_index = self._resolve_target_index(selected.get("target", ""))
                if target_index is None:
                    self._finish(completed=True)
                    return
                self._advance_to(target_index)
                return

            current_page = self.pages[self.page_index]
            explicit_next = str(current_page.get("next", "")).strip()
            target_index = self._resolve_target_index(explicit_next)
            if target_index is None:
                self._finish(completed=True)
                return
            self._advance_to(target_index)
            return

        self._render_page(self.app.tr("game.story.invalid"))

    def _story_progress_bar(self, current: int, total: int) -> str:
        width = 30
        ratio = current / total if total > 0 else 1.0
        filled = int(width * ratio)
        bar = ("#" * filled) + ("-" * (width - filled))
        percent = int(ratio * 100)
        return self.app.tr("game.story.progress", bar=bar, percent=percent)

    def _render_page(self, message: str = "") -> None:
        page = self.pages[self.page_index]
        title = self.app.tr("game.story.title", title=self.story_title)
        chapter = str(page.get("chapter", self.app.tr("game.story.chapter_default")))
        chapter_page = int(page.get("chapter_page", 1))
        text = str(page.get("text", ""))
        total = len(self.pages)
        current = self.page_index + 1
        mood = str(page.get("mood", "")).strip() or self.app.tr("game.story.mood_line")
        route = str(page.get("route", "")).strip()

        if route:
            self.app.on_story_route_entered(route)
        unlocked_messages = self._unlock_page_secrets(page)

        fx = str(page.get("fx", "")).strip().lower()
        if fx == "glitch":
            self.app.ui.trigger_glitch(0.55)

        choices = self._current_page_choices()
        selected = self._selected_choice(choices)

        lines = [
            title,
            "==========================================",
            self._story_progress_bar(current=current, total=total),
            self.app.tr("game.story.chapter_page", chapter=chapter, page=chapter_page),
            mood,
            "",
            text,
            "",
        ]

        if choices:
            lines.append(self.app.tr("game.story.choice_title"))
            for index, choice in enumerate(choices, start=1):
                mark = "*" if selected is not None and choice["flag"] == selected["flag"] else " "
                lines.append(
                    self.app.tr(
                        "game.story.choice_item",
                        idx=index,
                        mark=mark,
                        label=choice["label"],
                    )
                )
            lines.append("")

        controls_key = "game.story.controls_choice" if choices else "game.story.controls"
        lines.append(self.app.tr(controls_key, current=current, total=total))
        lines.append(
            self.app.tr(
                "game.story.secrets_meter",
                unlocked=len(self.secret_unlocked_ids),
                total=len(self.secret_files),
            )
        )
        if message:
            lines.extend(["", message])
        if unlocked_messages:
            lines.extend(["", *unlocked_messages])

        self.app.ui.set_screen("\n".join(lines))
        self.app.audio.play("message")
        self.app.on_story_progress(
            page=self.page_index + 1,
            total=len(self.pages),
            title=self.story_title,
        )

    def _finish(self, completed: bool) -> None:
        self.active = False
        self.page_history = []
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
