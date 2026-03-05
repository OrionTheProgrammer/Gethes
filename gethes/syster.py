from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from difflib import get_close_matches
import json
import os
import re
import unicodedata
from typing import Callable
from urllib import error, request


SYSTER_MODES = {"off", "lite", "lore", "hybrid"}


FOLLOW_UP_TOKENS = {
    "y",
    "y eso",
    "mas",
    "mas info",
    "sigue",
    "continua",
    "continue",
    "more",
    "and",
    "and then",
    "elabora",
    "detalle",
}


INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "help": ("help", "ayuda", "ajuda", "comando", "command", "commands"),
    "story": ("story", "historia", "capitulo", "chapter", "lore", "syster"),
    "save": ("save", "guardar", "checkpoint", "salvar", "savegame"),
    "profile": ("slot", "perfil", "profile", "ruta", "route", "slots"),
    "games": (
        "juego",
        "jugar",
        "game",
        "play",
        "snake",
        "ahorcado",
        "hangman",
        "gato",
        "tictactoe",
        "codebreaker",
        "codigo",
    ),
    "settings": (
        "theme",
        "tema",
        "options",
        "opciones",
        "config",
        "graphics",
        "idioma",
        "language",
        "uiscale",
    ),
    "update": (
        "update",
        "actualizar",
        "actualizo",
        "atualizar",
        "atualizo",
        "version",
        "patch",
        "release",
    ),
    "audio": (
        "sfx",
        "sonido",
        "som",
        "audio",
        "ruido",
        "sound",
        "freesound",
        "musica",
        "mute",
    ),
    "mods": ("mod", "mods", "modding", "tema mod", "story mod"),
    "creator": ("creator", "creador", "orion", "secreto", "secret", "gethes"),
    "identity": ("quien eres", "quien sos", "who are you", "quem e voce", "eres syster"),
    "greet": ("hola", "hello", "hi", "oi", "buenas", "hey"),
    "thanks": ("gracias", "thanks", "obrigado", "thx", "vale"),
    "achievements": ("logros", "achievement", "achievements", "conquistas", "trofeo", "trofeos"),
}


INTENT_TO_COMMAND = {
    "help": "help",
    "story": "historia",
    "save": "savegame",
    "profile": "slots",
    "games": "snake",
    "settings": "options",
    "update": "update status",
    "audio": "sfx doctor",
    "mods": "theme list",
    "achievements": "logros",
}


@dataclass
class SysterContext:
    slot_id: int = 1
    route_name: str = "Route 1"
    story_page: int = 0
    story_total: int = 0
    achievements_unlocked: int = 0
    achievements_total: int = 0
    last_command: str = ""


class SysterAssistant:
    def __init__(
        self,
        mode: str = "lite",
        remote_endpoint: str | None = None,
        remote_timeout: float = 2.2,
    ) -> None:
        self.mode = mode if mode in SYSTER_MODES else "lite"
        self.last_intent = "unknown"
        self.memory: deque[tuple[str, str]] = deque(maxlen=8)
        self.remote_endpoint = (remote_endpoint or os.getenv("GETHES_SYSTER_ENDPOINT", "")).strip()
        self.remote_timeout = max(0.7, min(8.0, float(remote_timeout)))

        timeout_raw = os.getenv("GETHES_SYSTER_TIMEOUT", "").strip()
        if timeout_raw:
            try:
                self.remote_timeout = max(0.7, min(8.0, float(timeout_raw)))
            except ValueError:
                pass

    def set_mode(self, mode: str) -> bool:
        if mode not in SYSTER_MODES:
            return False
        self.mode = mode
        return True

    def has_remote_endpoint(self) -> bool:
        return bool(self.remote_endpoint)

    def set_remote_endpoint(self, endpoint: str | None) -> None:
        self.remote_endpoint = (endpoint or "").strip()

    def reply(
        self,
        prompt: str,
        tr: Callable[[str], str],
        context: SysterContext | None = None,
    ) -> str:
        if self.mode == "off":
            return tr("app.syster.reply.off")

        ctx = context or SysterContext()
        normalized = self._normalize_text(prompt)
        if not normalized:
            return tr("app.syster.reply.unknown")

        if self.mode == "hybrid":
            remote_reply = self._remote_reply(prompt.strip(), ctx)
            if remote_reply:
                self.last_intent = "remote"
                self.memory.append((normalized, "remote"))
                return remote_reply

        if self._is_follow_up(normalized):
            follow = self._follow_up_reply(tr, ctx)
            self.memory.append((normalized, "followup"))
            return follow

        intent = self._detect_intent(normalized)
        self.last_intent = intent
        self.memory.append((normalized, intent))

        if intent == "greet":
            return tr("app.syster.reply.greet")

        if intent == "thanks":
            return tr("app.syster.reply.thanks")

        if intent == "help":
            return tr("app.syster.reply.help")

        if intent == "story":
            if ctx.story_total > 0 and ctx.story_page < ctx.story_total:
                return tr(
                    "app.syster.reply.story_progress",
                    page=ctx.story_page,
                    total=ctx.story_total,
                )
            return tr("app.syster.reply.story")

        if intent == "save":
            return tr("app.syster.reply.save")

        if intent == "profile":
            return tr("app.syster.reply.profile", slot=ctx.slot_id, route=ctx.route_name)

        if intent == "games":
            return tr("app.syster.reply.games")

        if intent == "settings":
            return tr("app.syster.reply.settings")

        if intent == "update":
            return tr("app.syster.reply.update")

        if intent == "audio":
            return tr("app.syster.reply.audio")

        if intent == "mods":
            return tr("app.syster.reply.mods")

        if intent == "identity":
            return tr("app.syster.reply.identity")

        if intent == "achievements":
            return tr(
                "app.syster.reply.achievement_progress",
                unlocked=ctx.achievements_unlocked,
                total=ctx.achievements_total,
            )

        if intent == "creator":
            base = tr("app.syster.reply.creator")
            if self.mode == "lore":
                return f"{base} {tr('app.syster.reply.lore')}"
            return base

        if self.mode == "lore":
            return f"{tr('app.syster.reply.unknown')} {tr('app.syster.reply.lore')}"

        hint_cmd = self._suggest_command(intent, ctx)
        return tr("app.syster.reply.hint", cmd=hint_cmd)

    def _follow_up_reply(self, tr: Callable[[str], str], context: SysterContext) -> str:
        if self.last_intent in {
            "story",
            "save",
            "profile",
            "games",
            "settings",
            "achievements",
            "update",
            "audio",
            "mods",
        }:
            hint_cmd = self._suggest_command(self.last_intent, context)
            return tr("app.syster.reply.followup", cmd=hint_cmd)

        if self.mode == "lore":
            return tr("app.syster.reply.lore")

        hint_cmd = self._suggest_command("help", context)
        return tr("app.syster.reply.hint", cmd=hint_cmd)

    def _remote_reply(self, prompt: str, context: SysterContext) -> str | None:
        if not self.has_remote_endpoint():
            return None

        payload = {
            "prompt": prompt,
            "context": asdict(context),
            "memory": self._memory_payload(),
            "agent": "Syster",
            "version": "0.03",
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.remote_endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain",
                "User-Agent": "Gethes-Syster/0.03",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.remote_timeout) as resp:
                raw = resp.read()
        except (error.URLError, error.HTTPError, TimeoutError, ValueError):
            return None

        if not raw:
            return None

        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            return None

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return " ".join(text.split())[:420]

        if isinstance(parsed, dict):
            for key in ("reply", "message", "text", "content"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return " ".join(value.split())[:420]
        return None

    def _memory_payload(self) -> list[dict[str, str]]:
        rows = list(self.memory)[-4:]
        return [{"prompt": prompt, "intent": intent} for prompt, intent in rows]

    def _detect_intent(self, text: str) -> str:
        scores = {key: 0 for key in INTENT_KEYWORDS}
        padded = f" {text} "

        for intent, words in INTENT_KEYWORDS.items():
            for word in words:
                token = f" {word} "
                if token in padded:
                    scores[intent] += 3
                elif word in text:
                    scores[intent] += 1

        best_intent = "unknown"
        best_score = 0
        for intent, score in scores.items():
            if score > best_score:
                best_score = score
                best_intent = intent

        if best_score > 0:
            return best_intent

        words = [token for token in re.split(r"\s+", text) if token]
        if not words:
            return "unknown"

        known = {w for items in INTENT_KEYWORDS.values() for w in items}
        for token in words:
            match = get_close_matches(token, known, n=1, cutoff=0.86)
            if not match:
                continue
            near = match[0]
            for intent, intents_words in INTENT_KEYWORDS.items():
                if near in intents_words:
                    return intent

        return "unknown"

    def _suggest_command(self, intent: str, context: SysterContext) -> str:
        suggested = INTENT_TO_COMMAND.get(intent, "help")
        if context.last_command and context.last_command not in {"syster", ""}:
            if intent in {"unknown", "help"}:
                return context.last_command
        return suggested

    @staticmethod
    def _is_follow_up(text: str) -> bool:
        if text in FOLLOW_UP_TOKENS:
            return True
        return text.startswith("y ") or text.startswith("and ")

    @staticmethod
    def _normalize_text(value: str) -> str:
        raw = value.strip().lower()
        if not raw:
            return ""
        decomposed = unicodedata.normalize("NFD", raw)
        clean = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
        return " ".join(clean.split())
