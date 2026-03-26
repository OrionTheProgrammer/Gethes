from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from difflib import get_close_matches
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import unicodedata
import zipfile
from typing import Callable
from urllib import error, request

from . import __version__
from .syster_memory import SysterKnowledgeStore

try:
    import httpx
except ImportError:  # pragma: no cover - optional dependency fallback
    httpx = None

try:
    from rapidfuzz import process as rapid_process
except ImportError:  # pragma: no cover - optional dependency fallback
    rapid_process = None

try:
    from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential
except ImportError:  # pragma: no cover - optional dependency fallback
    Retrying = None
    retry_if_exception_type = None
    stop_after_attempt = None
    wait_exponential = None


SYSTER_MODES = {"local"}
SYSTER_REQUIRED_MODEL = "mistral"
SYSTER_OLLAMA_RUNTIME_WINDOWS_URL = (
    "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip"
)


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
    "rogue": (
        "rogue",
        "roguelike",
        "rogelike",
        "dungeon",
        "mazmorra",
        "expedicion",
        "floor",
        "piso",
        "andar",
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
    "diagnostics": (
        "doctor",
        "diag",
        "diagnostico",
        "diagnostics",
        "error",
        "errores",
        "bug",
        "issue",
        "problema",
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
    "rogue": "roguelike",
    "settings": "options",
    "update": "update status",
    "audio": "sfx doctor",
    "diagnostics": "doctor all",
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
    rogue_runs: int = 0
    rogue_wins: int = 0
    rogue_best_depth: int = 0
    last_command: str = ""
    player_name: str = ""
    language: str = ""
    active_theme: str = ""
    sound_enabled: bool = True
    graphics_level: str = "medium"
    ui_scale: float = 1.0
    recent_commands: list[str] = field(default_factory=list)
    recent_events: list[str] = field(default_factory=list)
    best_scores: dict[str, int] = field(default_factory=dict)
    unlocked_themes: list[str] = field(default_factory=list)


class SysterAssistant:
    def __init__(
        self,
        mode: str = "local",
        remote_endpoint: str | None = None,
        remote_timeout: float = 2.2,
        ollama_enabled: bool = True,
        ollama_model: str = "mistral",
        ollama_host: str | None = None,
        ollama_timeout: float = 24.0,
        ollama_runtime_path: str | None = None,
        package_dir: Path | str | None = None,
        storage_dir: Path | str | None = None,
        knowledge_store: SysterKnowledgeStore | None = None,
        ollama_autostart: bool = True,
        ollama_auto_pull: bool = True,
        ollama_context_length: int = 4096,
        ollama_flash_attention: bool = True,
        ollama_kv_cache_type: str = "q8_0",
        ollama_keep_alive: str = "20m",
    ) -> None:
        self.mode = "local"
        self.last_intent = "unknown"
        self.memory: deque[tuple[str, str]] = deque(maxlen=8)
        self.remote_endpoint = ""
        self.remote_timeout = max(0.7, min(8.0, float(remote_timeout)))
        self.ollama_enabled = True
        self.ollama_model = SYSTER_REQUIRED_MODEL
        self.ollama_host = self._normalize_ollama_host(
            (ollama_host or os.getenv("GETHES_OLLAMA_HOST", "http://127.0.0.1:11434")).strip()
        )
        self.ollama_timeout = max(1.0, min(120.0, float(ollama_timeout)))
        self.ollama_status_cache_ok = False
        self.ollama_status_cache_error = "not_checked"
        self.ollama_last_probe_ts = 0.0
        self.ollama_probe_interval = 15.0
        self.ollama_runtime_path = (ollama_runtime_path or "").strip()
        self.ollama_autostart = bool(ollama_autostart)
        self.ollama_auto_pull = bool(ollama_auto_pull)
        self.ollama_context_length = max(1024, min(32768, int(ollama_context_length)))
        self.ollama_flash_attention = bool(ollama_flash_attention)
        self.ollama_kv_cache_type = (
            ollama_kv_cache_type.strip().lower() if ollama_kv_cache_type else "q8_0"
        )
        if self.ollama_kv_cache_type not in {"f16", "q8_0", "q4_0"}:
            self.ollama_kv_cache_type = "q8_0"
        keep_alive_token = (ollama_keep_alive or "").strip()
        self.ollama_keep_alive = keep_alive_token or "20m"
        self.knowledge_store = knowledge_store
        self.package_dir = Path(package_dir) if package_dir else None
        self.storage_dir = Path(storage_dir) if storage_dir else None
        self._ollama_exec_cache = ""
        self._ollama_server_lock = threading.Lock()
        self._ollama_pull_lock = threading.Lock()
        self._ollama_last_launch_attempt = 0.0
        self._ollama_pull_in_progress = False
        self._ollama_model_ready = False
        self._ollama_model_check_ts = 0.0
        self._runtime_bootstrap_lock = threading.Lock()
        self._runtime_bootstrap_in_progress = False
        self._runtime_bootstrap_last_attempt = 0.0
        self._runtime_bootstrap_last_error = ""
        self._runtime_bootstrap_url = (
            os.getenv("GETHES_OLLAMA_RUNTIME_URL", SYSTER_OLLAMA_RUNTIME_WINDOWS_URL).strip()
            or SYSTER_OLLAMA_RUNTIME_WINDOWS_URL
        )

        timeout_raw = os.getenv("GETHES_SYSTER_TIMEOUT", "").strip()
        if timeout_raw:
            try:
                self.remote_timeout = max(0.7, min(8.0, float(timeout_raw)))
            except ValueError:
                pass

        ollama_timeout_raw = os.getenv("GETHES_OLLAMA_TIMEOUT", "").strip()
        if ollama_timeout_raw:
            try:
                self.ollama_timeout = max(1.0, min(120.0, float(ollama_timeout_raw)))
            except ValueError:
                pass

        context_raw = os.getenv("GETHES_OLLAMA_CONTEXT", "").strip() or os.getenv(
            "OLLAMA_CONTEXT_LENGTH", ""
        ).strip()
        if context_raw:
            try:
                self.ollama_context_length = max(1024, min(32768, int(float(context_raw))))
            except ValueError:
                pass

        flash_raw = os.getenv("GETHES_OLLAMA_FLASH_ATTENTION", "").strip() or os.getenv(
            "OLLAMA_FLASH_ATTENTION", ""
        ).strip()
        if flash_raw:
            self.ollama_flash_attention = flash_raw.lower() in {"1", "true", "on", "yes"}

        kv_raw = os.getenv("GETHES_OLLAMA_KV_CACHE_TYPE", "").strip() or os.getenv(
            "OLLAMA_KV_CACHE_TYPE", ""
        ).strip()
        if kv_raw.lower() in {"f16", "q8_0", "q4_0"}:
            self.ollama_kv_cache_type = kv_raw.lower()

        keep_alive_raw = os.getenv("GETHES_OLLAMA_KEEP_ALIVE", "").strip() or os.getenv(
            "OLLAMA_KEEP_ALIVE", ""
        ).strip()
        if keep_alive_raw:
            self.ollama_keep_alive = keep_alive_raw

    def set_mode(self, mode: str) -> bool:
        if mode != "local":
            return False
        self.mode = "local"
        return True

    def has_remote_endpoint(self) -> bool:
        return False

    def set_remote_endpoint(self, endpoint: str | None) -> None:
        self.remote_endpoint = ""

    def set_ollama_enabled(self, enabled: bool) -> None:
        self.ollama_enabled = True
        self.ollama_last_probe_ts = 0.0
        self.warmup_local_ai()

    def set_ollama_model(self, model: str) -> None:
        self.ollama_model = SYSTER_REQUIRED_MODEL
        self._ollama_model_ready = False
        self._ollama_model_check_ts = 0.0

    def set_ollama_host(self, host: str | None) -> None:
        self.ollama_host = self._normalize_ollama_host((host or "").strip())
        self.ollama_last_probe_ts = 0.0
        self._ollama_model_ready = False
        self._ollama_model_check_ts = 0.0

    def set_ollama_timeout(self, timeout_seconds: float) -> None:
        self.ollama_timeout = max(1.0, min(120.0, float(timeout_seconds)))

    def set_ollama_context_length(self, tokens: int) -> None:
        self.ollama_context_length = max(1024, min(32768, int(tokens)))

    def set_ollama_flash_attention(self, enabled: bool) -> None:
        self.ollama_flash_attention = bool(enabled)

    def set_ollama_kv_cache_type(self, kv_type: str) -> None:
        token = (kv_type or "").strip().lower()
        if token in {"f16", "q8_0", "q4_0"}:
            self.ollama_kv_cache_type = token

    def set_ollama_keep_alive(self, value: str) -> None:
        token = (value or "").strip()
        if token:
            self.ollama_keep_alive = token

    def warmup_local_ai(self) -> None:
        if not self.ollama_enabled:
            return

        def worker() -> None:
            self._start_runtime_bootstrap_async()
            self._probe_ollama(force=True)
            self._check_ollama_model_ready(force=True)

        threading.Thread(target=worker, daemon=True, name="syster-ai-warmup").start()

    def get_ollama_status(self, force_probe: bool = False) -> tuple[bool, str]:
        if not self.ollama_enabled:
            return False, "disabled"
        if not self.ollama_host:
            return False, "missing_host"
        ok, reason = self._probe_ollama(force=force_probe)
        return ok, reason

    def core_runtime_status(self, force_probe: bool = False) -> dict[str, object]:
        online, state = self.get_ollama_status(force_probe=force_probe)
        runtime_path = self._resolve_ollama_executable()
        models_dir = self._resolve_ollama_models_dir()
        model_ready = self._model_exists_in_runtime() if online else self._ollama_model_ready
        cuda_available = self._detect_cuda_driver()
        return {
            "enabled": self.ollama_enabled,
            "online": online,
            "state": state,
            "model": self.ollama_model,
            "host": self.ollama_host,
            "runtime_path": runtime_path,
            "models_dir": str(models_dir),
            "model_ready": model_ready,
            "context_length": self.ollama_context_length,
            "flash_attention": self.ollama_flash_attention,
            "kv_cache_type": self.ollama_kv_cache_type,
            "keep_alive": self.ollama_keep_alive,
            "cuda_available": cuda_available,
            "runtime_bootstrap_in_progress": self._runtime_bootstrap_in_progress,
            "runtime_bootstrap_error": self._runtime_bootstrap_last_error,
        }

    def optimize_for_cuda(self, profile: str = "balanced") -> dict[str, object]:
        token = (profile or "balanced").strip().lower()
        if token not in {"balanced", "quality", "speed"}:
            token = "balanced"

        if token == "quality":
            self.ollama_context_length = 8192
            self.ollama_kv_cache_type = "f16"
            self.ollama_keep_alive = "30m"
        elif token == "speed":
            self.ollama_context_length = 4096
            self.ollama_kv_cache_type = "q8_0"
            self.ollama_keep_alive = "15m"
        else:
            self.ollama_context_length = 6144
            self.ollama_kv_cache_type = "q8_0"
            self.ollama_keep_alive = "20m"

        self.ollama_flash_attention = True
        self.ollama_last_probe_ts = 0.0
        return {
            "profile": token,
            "context_length": self.ollama_context_length,
            "kv_cache_type": self.ollama_kv_cache_type,
            "flash_attention": self.ollama_flash_attention,
            "keep_alive": self.ollama_keep_alive,
        }

    def observe_exchange(
        self,
        *,
        prompt: str,
        reply: str,
        context: SysterContext | None,
        source: str,
        intent: str = "",
    ) -> None:
        if self.knowledge_store is None:
            return

        prompt_text = " ".join((prompt or "").split()).strip()
        reply_text = " ".join((reply or "").split()).strip()
        if not prompt_text and not reply_text:
            return

        language = context.language if context is not None else ""
        intent_token = (intent or self.last_intent or "").strip()
        if prompt_text:
            self.knowledge_store.record_interaction(
                "player",
                prompt_text,
                intent=intent_token,
                source=source,
                language=language,
            )
        if reply_text:
            self.knowledge_store.record_interaction(
                "syster",
                reply_text,
                intent=intent_token,
                source=source,
                language=language,
            )

        if context is None:
            return
        if context.player_name:
            self.knowledge_store.upsert_long_memory(
                "player_name",
                context.player_name,
                source="context",
                weight=2.0,
            )
        if context.route_name:
            self.knowledge_store.upsert_long_memory(
                "active_route",
                context.route_name,
                source="context",
                weight=1.2,
            )
        if context.active_theme:
            self.knowledge_store.upsert_long_memory(
                "active_theme",
                context.active_theme,
                source="context",
                weight=1.1,
            )
        if context.language:
            self.knowledge_store.upsert_long_memory(
                "language",
                context.language,
                source="context",
                weight=1.4,
            )
        scores = context.best_scores or {}
        if scores:
            compact_scores = ", ".join(
                f"{key}:{int(value)}"
                for key, value in sorted(scores.items())
                if isinstance(value, int)
            )
            if compact_scores:
                self.knowledge_store.upsert_long_memory(
                    "best_scores",
                    compact_scores[:700],
                    source="stats",
                    weight=1.3,
                )

    def record_feedback(self, prompt: str, reply: str, score: float, notes: str = "") -> None:
        if self.knowledge_store is None:
            return
        self.knowledge_store.record_feedback(prompt=prompt, reply=reply, score=score, notes=notes)

    @staticmethod
    def extract_control_command(reply: str) -> tuple[str, str]:
        if not reply:
            return "", ""
        lines = [line.rstrip() for line in reply.splitlines()]
        if not lines:
            return "", reply
        first = lines[0].strip()
        match = re.match(r"^\[\[\s*sys\s*:\s*([^\]]+)\s*\]\]$", first, flags=re.IGNORECASE)
        if not match:
            return "", reply
        command = " ".join(match.group(1).split())
        cleaned = "\n".join(lines[1:]).strip()
        return command, cleaned

    def reply(
        self,
        prompt: str,
        tr: Callable[[str], str],
        context: SysterContext | None = None,
    ) -> str:
        ctx = context or SysterContext()
        normalized = self._normalize_text(prompt)
        if not normalized:
            return tr("app.syster.reply.unknown")

        if normalized in {"brief", "briefing", "resumen", "estado", "status"}:
            self.last_intent = "briefing"
            self.memory.append((normalized, "briefing"))
            return self.briefing(tr, ctx)

        ollama_reply = self._ollama_reply(prompt.strip(), ctx)
        if ollama_reply:
            self.last_intent = "ollama"
            self.memory.append((normalized, "ollama"))
            return ollama_reply

        if self._is_follow_up(normalized):
            follow = self._follow_up_reply(tr, ctx)
            self.memory.append((normalized, "followup"))
            return follow

        intent = self._detect_intent(normalized)
        if intent == "unknown" and self.ollama_enabled:
            ok, reason = self._probe_ollama(force=True)
            if ok:
                reason = "response_empty"
            self.last_intent = "core_unavailable"
            self.memory.append((normalized, "core_unavailable"))
            return tr(
                "app.syster.reply.core_unavailable",
                model=self.ollama_model,
                reason=self._humanize_core_reason(reason),
            )

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

        if intent == "rogue":
            if ctx.rogue_runs > 0:
                return tr(
                    "app.syster.reply.rogue_progress",
                    runs=ctx.rogue_runs,
                    wins=ctx.rogue_wins,
                    depth=ctx.rogue_best_depth,
                )
            return tr("app.syster.reply.rogue")

        if intent == "settings":
            return tr("app.syster.reply.settings")

        if intent == "update":
            return tr("app.syster.reply.update")

        if intent == "audio":
            return tr("app.syster.reply.audio")

        if intent == "diagnostics":
            return tr("app.syster.reply.diagnostics")

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
            return base

        hint_cmd = self._suggest_command(intent, ctx)
        return tr("app.syster.reply.hint", cmd=hint_cmd)

    def briefing(self, tr: Callable[[str], str], context: SysterContext) -> str:
        recommended = self._recommend_next_command(context)
        return tr(
            "app.syster.reply.briefing",
            slot=context.slot_id,
            route=context.route_name,
            page=context.story_page,
            total=context.story_total,
            unlocked=context.achievements_unlocked,
            achievements=context.achievements_total,
            runs=context.rogue_runs,
            wins=context.rogue_wins,
            depth=context.rogue_best_depth,
            cmd=recommended,
        )

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

        hint_cmd = self._suggest_command("help", context)
        return tr("app.syster.reply.hint", cmd=hint_cmd)

    def _ollama_reply(self, prompt: str, context: SysterContext) -> str | None:
        if not self.ollama_enabled:
            return None
        if not prompt:
            return None
        if not self.ollama_host:
            return None

        ok, _ = self._probe_ollama(force=False)
        if not ok:
            return None

        payload = self._build_ollama_payload(prompt, context)
        text = self._ollama_reply_httpx(payload)
        if text is None:
            text = self._ollama_reply_urllib(payload)
        if not text:
            # Retry once after forcing a fresh probe to reduce transient local failures.
            self._probe_ollama(force=True)
            text = self._ollama_reply_httpx(payload)
            if text is None:
                text = self._ollama_reply_urllib(payload)
        if not text:
            return None
        return self._compact_reply(text)

    def _build_ollama_payload(self, prompt: str, context: SysterContext) -> dict[str, object]:
        system_prompt = (
            "You are Syster, the in-world assistant of Gethes. "
            "Reply naturally, concise, and immersive. "
            "Prioritize emotional support, story context, and gameplay guidance. "
            "Always respond in the same language as the player message (es/en/pt). "
            "Do not generate source code unless explicitly requested. "
            "Do not invent game mechanics, commands, or lore beyond provided context. "
            "When suggesting commands, use only known in-game commands from the allowed list. "
            "If asked for commands, return only commands from the list, never keyboard/mouse controls. "
            "If the player asks for a strict format or length (e.g. '2 lines'), obey it exactly. "
            "If uncertain, recommend `help`. "
            "When the user explicitly asks to change settings or open a mode, "
            "you may prepend the first line exactly as [[sys:<internal_command>]] "
            "using a single safe in-game command."
        )
        best_scores = context.best_scores or {}
        context_lines = [
            f"player={context.player_name}",
            f"language={context.language}",
            f"slot={context.slot_id}",
            f"route={context.route_name}",
            f"story={context.story_page}/{context.story_total}",
            f"achievements={context.achievements_unlocked}/{context.achievements_total}",
            f"rogue_runs={context.rogue_runs}",
            f"rogue_wins={context.rogue_wins}",
            f"rogue_best_depth={context.rogue_best_depth}",
            f"last_command={context.last_command}",
            f"theme={context.active_theme}",
            f"sound={'on' if context.sound_enabled else 'off'}",
            f"graphics={context.graphics_level}",
            f"ui_scale={context.ui_scale:.2f}",
            f"snake_best={best_scores.get('snake_best_score', 0)}",
            f"rogue_best_gold={best_scores.get('rogue_best_gold', 0)}",
        ]
        if context.recent_commands:
            context_lines.append(f"recent_commands={'; '.join(context.recent_commands[-5:])}")
        if context.recent_events:
            context_lines.append(f"recent_events={'; '.join(context.recent_events[-5:])}")
        if context.unlocked_themes:
            context_lines.append(f"unlocked_themes={'; '.join(context.unlocked_themes[:8])}")

        long_memory_block = "none"
        feedback_block = "none"
        if self.knowledge_store is not None:
            memories = self.knowledge_store.get_long_memory_entries(limit=6, min_weight=0.9)
            if memories:
                long_memory_block = " | ".join(
                    f"{row['key']}={str(row['value'])[:120]}" for row in memories
                )
            feedback_items = self.knowledge_store.get_feedback_examples(limit=2, min_score=0.6)
            if feedback_items:
                feedback_block = " | ".join(
                    f"score={row['score']:.2f} note={str(row['notes'])[:80]}"
                    for row in feedback_items
                )

        memory_items = [f"{item['intent']}::{item['prompt']}" for item in self._memory_payload()[-3:]]
        memory_block = " | ".join(memory_items) if memory_items else "none"
        composed_prompt = (
            "Context: "
            + ", ".join(context_lines)
            + f"\nRecent memory: {memory_block}\n"
            + f"Long memory: {long_memory_block}\n"
            + f"Training feedback: {feedback_block}\n"
            + "Allowed commands: help, menu, clear, snake, ahorcado1, ahorcado2, historia, "
            + "gato, codigo, physics, roguelike, daily status, logros, slots, slot <1-3>, "
            + "savegame, options, theme list, theme <preset>, uiscale <valor>, "
            + "sound <on|off>, graphics <low|medium|high>, lang <modo>, syster brief, "
            + "syster train status\n"
            + f"Player says: {prompt}\nSyster:"
        )
        return {
            "model": self.ollama_model,
            "system": system_prompt,
            "prompt": composed_prompt,
            "stream": False,
            "keep_alive": self.ollama_keep_alive,
            "options": {
                "temperature": 0.65,
                "top_p": 0.92,
                "repeat_penalty": 1.08,
                "num_predict": 280,
                "num_ctx": self.ollama_context_length,
            },
        }

    def _probe_ollama(self, force: bool = False) -> tuple[bool, str]:
        if not self.ollama_enabled:
            self.ollama_status_cache_ok = False
            self.ollama_status_cache_error = "disabled"
            return False, "disabled"
        if not self.ollama_host:
            self.ollama_status_cache_ok = False
            self.ollama_status_cache_error = "missing_host"
            return False, "missing_host"

        now = time.monotonic()
        if not force and (now - self.ollama_last_probe_ts) < self.ollama_probe_interval:
            return self.ollama_status_cache_ok, self.ollama_status_cache_error

        self.ollama_last_probe_ts = now
        ok, reason = self._probe_ollama_http()
        if not ok and self.ollama_autostart:
            self._ensure_ollama_server_running()
            ok, reason = self._probe_ollama_http()

        if not ok:
            runtime_exe = self._resolve_ollama_executable()
            if not runtime_exe:
                self._start_runtime_bootstrap_async()
                if self._runtime_bootstrap_in_progress:
                    reason = "runtime_downloading"
                elif self._runtime_bootstrap_last_error:
                    reason = "runtime_bootstrap_failed"
                else:
                    reason = "runtime_missing"

        if ok:
            model_ok, model_reason = self._check_ollama_model_ready(force=force)
            if not model_ok:
                ok = False
                reason = model_reason
            else:
                reason = "online"

        self.ollama_status_cache_ok = ok
        self.ollama_status_cache_error = reason
        return ok, reason

    def _probe_ollama_http(self) -> tuple[bool, str]:
        probe_url = f"{self.ollama_host}/api/version"
        timeout_seconds = max(0.35, min(1.8, self.ollama_timeout * 0.12))

        if httpx is not None:
            try:
                timeout = httpx.Timeout(timeout_seconds)
                with httpx.Client(timeout=timeout) as client:
                    resp = client.get(probe_url)
                if resp.status_code < 400:
                    return True, "online"
                return False, f"http_{resp.status_code}"
            except (httpx.RequestError, httpx.TimeoutException, ValueError):
                return False, "unreachable"

        req = request.Request(
            probe_url,
            headers={
                "Accept": "application/json, text/plain",
                "User-Agent": f"Gethes-Syster/{__version__}",
            },
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=timeout_seconds):
                return True, "online"
        except (error.URLError, error.HTTPError, TimeoutError, ValueError):
            return False, "unreachable"

    def _resolve_ollama_executable(self) -> str:
        if self._ollama_exec_cache and Path(self._ollama_exec_cache).exists():
            return self._ollama_exec_cache

        candidates: list[Path] = []
        if self.ollama_runtime_path:
            candidates.append(Path(self.ollama_runtime_path))
        if self.package_dir is not None:
            candidates.append(self.package_dir / "vendor" / "syster_core" / "ollama" / "ollama.exe")
            candidates.append(self.package_dir / "vendor" / "ollama" / "ollama.exe")
        if self.storage_dir is not None:
            candidates.append(self.storage_dir / "syster_runtime" / "ollama" / "ollama.exe")
        local_appdata = os.getenv("LOCALAPPDATA", "")
        if local_appdata:
            candidates.append(Path(local_appdata) / "Programs" / "Ollama" / "ollama.exe")

        for candidate in candidates:
            try:
                if candidate.exists():
                    self._ollama_exec_cache = str(candidate)
                    return self._ollama_exec_cache
            except OSError:
                continue

        from_path = shutil.which("ollama")
        if from_path:
            self._ollama_exec_cache = from_path
            return from_path
        return ""

    def _resolve_ollama_models_dir(self) -> Path:
        if self.package_dir is not None:
            bundled_candidates = [
                self.package_dir / "vendor" / "syster_core" / "models",
                self.package_dir / "vendor" / "models",
            ]
            for bundled in bundled_candidates:
                if (bundled / "manifests").exists() and (bundled / "blobs").exists():
                    return bundled

        if self.storage_dir is not None:
            target = self.storage_dir / "ai_models"
            target.mkdir(parents=True, exist_ok=True)
            return target

        fallback = Path.home() / ".ollama" / "models"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def _start_runtime_bootstrap_async(self) -> None:
        if os.name != "nt":
            return
        if self.storage_dir is None:
            return
        if self._resolve_ollama_executable():
            return

        now = time.monotonic()
        if (now - self._runtime_bootstrap_last_attempt) < 20.0:
            return

        with self._runtime_bootstrap_lock:
            now_locked = time.monotonic()
            if self._runtime_bootstrap_in_progress:
                return
            if (now_locked - self._runtime_bootstrap_last_attempt) < 20.0:
                return
            self._runtime_bootstrap_last_attempt = now_locked
            self._runtime_bootstrap_in_progress = True
            self._runtime_bootstrap_last_error = ""

        def worker() -> None:
            try:
                runtime_root = self.storage_dir / "syster_runtime"
                downloads_dir = runtime_root / "downloads"
                extract_dir = runtime_root / "_extract"
                runtime_dir = runtime_root / "ollama"
                archive_path = downloads_dir / "ollama-windows-amd64.zip"

                downloads_dir.mkdir(parents=True, exist_ok=True)
                if extract_dir.exists():
                    shutil.rmtree(extract_dir, ignore_errors=True)
                extract_dir.mkdir(parents=True, exist_ok=True)

                req = request.Request(
                    self._runtime_bootstrap_url,
                    headers={
                        "User-Agent": f"Gethes-Syster/{__version__}",
                        "Accept": "*/*",
                    },
                    method="GET",
                )
                with request.urlopen(req, timeout=150) as response, archive_path.open("wb") as target:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        target.write(chunk)

                with zipfile.ZipFile(archive_path) as zipped:
                    zipped.extractall(extract_dir)

                found_exe: Path | None = None
                for candidate in extract_dir.rglob("ollama.exe"):
                    if candidate.is_file():
                        found_exe = candidate
                        break
                if found_exe is None:
                    raise RuntimeError("runtime_archive_missing_ollama_exe")

                source_root = found_exe.parent
                if runtime_dir.exists():
                    shutil.rmtree(runtime_dir, ignore_errors=True)
                shutil.copytree(source_root, runtime_dir)

                self.ollama_runtime_path = str(runtime_dir / "ollama.exe")
                self._ollama_exec_cache = ""
                self._runtime_bootstrap_last_error = ""
            except Exception as exc:
                self._runtime_bootstrap_last_error = str(exc)[:220]
            finally:
                with self._runtime_bootstrap_lock:
                    self._runtime_bootstrap_in_progress = False

        threading.Thread(target=worker, daemon=True, name="syster-ai-runtime-bootstrap").start()

    def _ollama_runtime_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["OLLAMA_HOST"] = self.ollama_host
        env["OLLAMA_MODELS"] = str(self._resolve_ollama_models_dir())
        env["OLLAMA_CONTEXT_LENGTH"] = str(self.ollama_context_length)
        env["OLLAMA_FLASH_ATTENTION"] = "1" if self.ollama_flash_attention else "0"
        env["OLLAMA_KV_CACHE_TYPE"] = self.ollama_kv_cache_type
        env["OLLAMA_KEEP_ALIVE"] = self.ollama_keep_alive
        env.setdefault("OLLAMA_NUM_PARALLEL", "1")
        env.setdefault("OLLAMA_MAX_QUEUE", "4")
        return env

    def _ensure_ollama_server_running(self) -> None:
        now = time.monotonic()
        if (now - self._ollama_last_launch_attempt) < 4.0:
            return
        with self._ollama_server_lock:
            now_locked = time.monotonic()
            if (now_locked - self._ollama_last_launch_attempt) < 4.0:
                return
            self._ollama_last_launch_attempt = now_locked
            exe = self._resolve_ollama_executable()
            if not exe:
                self._start_runtime_bootstrap_async()
                return
            flags = 0
            flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            flags |= int(getattr(subprocess, "DETACHED_PROCESS", 0))
            try:
                subprocess.Popen(
                    [exe, "serve"],
                    env=self._ollama_runtime_env(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=flags,
                )
            except Exception:
                return
            deadline = time.monotonic() + 5.5
            while time.monotonic() < deadline:
                ok, _ = self._probe_ollama_http()
                if ok:
                    return
                time.sleep(0.22)

    def _check_ollama_model_ready(self, force: bool = False) -> tuple[bool, str]:
        now = time.monotonic()
        if not force and self._ollama_model_ready and (now - self._ollama_model_check_ts) < 60.0:
            return True, "model_ready"
        self._ollama_model_check_ts = now
        found = self._model_exists_in_runtime()
        if found:
            self._ollama_model_ready = True
            return True, "model_ready"
        self._ollama_model_ready = False
        if self.ollama_auto_pull:
            self._start_ollama_model_pull_async()
            return False, "model_downloading"
        return False, "model_missing"

    def _model_exists_in_runtime(self) -> bool:
        host = self.ollama_host
        if not host:
            return False
        tags_url = f"{host}/api/tags"
        expected = self.ollama_model.strip().lower()
        candidates = {expected}
        if ":" not in expected:
            candidates.add(f"{expected}:latest")
        if expected.endswith(":latest"):
            candidates.add(expected.split(":", 1)[0])

        if httpx is not None:
            try:
                timeout = httpx.Timeout(max(0.8, min(4.0, self.ollama_timeout * 0.3)))
                with httpx.Client(timeout=timeout) as client:
                    resp = client.get(tags_url)
                if resp.status_code >= 400:
                    return False
                payload = resp.json()
            except Exception:
                return False
        else:
            req = request.Request(tags_url, method="GET")
            try:
                with request.urlopen(req, timeout=max(0.8, min(4.0, self.ollama_timeout * 0.3))) as resp:
                    payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            except Exception:
                return False

        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return False
        for item in models:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip().lower()
            if name in candidates:
                return True
        return False

    def _start_ollama_model_pull_async(self) -> None:
        if self._ollama_pull_in_progress:
            return

        def worker() -> None:
            with self._ollama_pull_lock:
                self._ollama_pull_in_progress = True
                try:
                    exe = self._resolve_ollama_executable()
                    if not exe:
                        return
                    subprocess.run(
                        [exe, "pull", self.ollama_model],
                        env=self._ollama_runtime_env(),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=1800,
                    )
                    self._ollama_model_ready = self._model_exists_in_runtime()
                    self._ollama_model_check_ts = time.monotonic()
                except Exception:
                    return
                finally:
                    self._ollama_pull_in_progress = False

        threading.Thread(target=worker, daemon=True, name="syster-ai-model-pull").start()

    def _ollama_reply_httpx(self, payload: dict[str, object]) -> str | None:
        if httpx is None:
            return None
        if not self.ollama_host:
            return None

        url = f"{self.ollama_host}/api/generate"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain",
            "User-Agent": f"Gethes-Syster/{__version__}",
        }

        try:
            timeout = httpx.Timeout(self.ollama_timeout)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                return None
            try:
                parsed = resp.json()
            except ValueError:
                return self._parse_remote_text(resp.text)
            return self._extract_ollama_text(parsed)
        except (httpx.RequestError, httpx.TimeoutException, ValueError):
            return None

    def _ollama_reply_urllib(self, payload: dict[str, object]) -> str | None:
        if not self.ollama_host:
            return None
        url = f"{self.ollama_host}/api/generate"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain",
                "User-Agent": f"Gethes-Syster/{__version__}",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.ollama_timeout) as resp:
                raw = resp.read()
        except (error.URLError, error.HTTPError, TimeoutError, ValueError):
            return None

        if not raw:
            return None
        text = raw.decode("utf-8", errors="replace").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return self._parse_remote_text(text)
        return self._extract_ollama_text(parsed)

    @staticmethod
    def _extract_ollama_text(parsed: object) -> str | None:
        if not isinstance(parsed, dict):
            return None
        response = parsed.get("response")
        if isinstance(response, str) and response.strip():
            return response.strip()
        message = parsed.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        return None

    def _remote_reply(self, prompt: str, context: SysterContext) -> str | None:
        if not self.has_remote_endpoint():
            return None

        payload = {
            "prompt": prompt,
            "context": asdict(context),
            "memory": self._memory_payload(),
            "agent": "Syster",
            "version": __version__,
        }
        text = self._remote_reply_httpx(payload)
        if text is None:
            text = self._remote_reply_urllib(payload)
        if not text:
            return None
        return self._parse_remote_text(text)

    def _remote_reply_httpx(self, payload: dict[str, object]) -> str | None:
        if httpx is None:
            return None
        if not self.has_remote_endpoint():
            return None

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain",
            "User-Agent": f"Gethes-Syster/{__version__}",
        }

        def send_once() -> str:
            assert httpx is not None
            timeout = httpx.Timeout(self.remote_timeout)
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(self.remote_endpoint, json=payload, headers=headers)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"server_error_{resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                if resp.status_code >= 400:
                    return ""
                return resp.text

        try:
            if (
                Retrying is not None
                and retry_if_exception_type is not None
                and stop_after_attempt is not None
                and wait_exponential is not None
            ):
                retryer = Retrying(
                    reraise=True,
                    stop=stop_after_attempt(2),
                    wait=wait_exponential(multiplier=0.25, min=0.25, max=1.4),
                    retry=retry_if_exception_type(
                        (
                            httpx.RequestError,
                            httpx.TimeoutException,
                            httpx.HTTPStatusError,
                        )
                    ),
                )
                for attempt in retryer:
                    with attempt:
                        return send_once().strip()
                return None
            return send_once().strip()
        except (
            httpx.RequestError,
            httpx.TimeoutException,
            httpx.HTTPStatusError,
            ValueError,
        ):
            return None

    def _remote_reply_urllib(self, payload: dict[str, object]) -> str | None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            self.remote_endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain",
                "User-Agent": f"Gethes-Syster/{__version__}",
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
        return raw.decode("utf-8", errors="replace").strip()

    @staticmethod
    def _parse_remote_text(text: str) -> str | None:
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
            near = self._closest_keyword(token, known)
            if not near:
                continue
            for intent, intents_words in INTENT_KEYWORDS.items():
                if near in intents_words:
                    return intent

        return "unknown"

    @staticmethod
    def _closest_keyword(token: str, known_words: set[str]) -> str:
        token_norm = token.strip()
        if not token_norm:
            return ""

        if rapid_process is not None:
            hit = rapid_process.extractOne(
                token_norm,
                list(known_words),
                score_cutoff=86,
            )
            if hit is not None:
                return str(hit[0])
            return ""

        match = get_close_matches(token_norm, known_words, n=1, cutoff=0.86)
        if match:
            return match[0]
        return ""

    def _suggest_command(self, intent: str, context: SysterContext) -> str:
        suggested = INTENT_TO_COMMAND.get(intent, "help")
        if context.last_command and context.last_command not in {"syster", ""}:
            if intent in {"unknown", "help"}:
                return context.last_command
        return suggested

    def _recommend_next_command(self, context: SysterContext) -> str:
        if context.story_total > 0 and context.story_page < context.story_total:
            return "historia"
        if context.rogue_runs <= 0:
            return "roguelike"
        if context.achievements_unlocked < context.achievements_total:
            return "logros"
        if context.last_command and context.last_command not in {"", "syster"}:
            return context.last_command
        return "help"

    @staticmethod
    def _is_follow_up(text: str) -> bool:
        if text in FOLLOW_UP_TOKENS:
            return True
        return text.startswith("y ") or text.startswith("and ")

    @staticmethod
    def _compact_reply(value: str) -> str:
        compact = "\n".join(line.strip() for line in value.strip().splitlines() if line.strip())
        compact = " ".join(compact.split()) if compact.count("\n") == 0 else compact
        max_len = 760
        if len(compact) <= max_len:
            return compact
        clipped = compact[:max_len]
        boundary = max(clipped.rfind(". "), clipped.rfind("! "), clipped.rfind("? "))
        if boundary >= 120:
            return clipped[: boundary + 1].strip()
        return clipped.strip()

    @staticmethod
    def _detect_cuda_driver() -> bool:
        cmd = shutil.which("nvidia-smi")
        if not cmd:
            return False
        try:
            proc = subprocess.run(
                [cmd, "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=1.8,
                check=False,
            )
            return proc.returncode == 0 and bool(proc.stdout.strip())
        except Exception:
            return False

    @staticmethod
    def _normalize_ollama_host(value: str) -> str:
        host = value.strip()
        if not host:
            return ""
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        return host.rstrip("/")

    @staticmethod
    def _normalize_text(value: str) -> str:
        raw = value.strip().lower()
        if not raw:
            return ""
        decomposed = unicodedata.normalize("NFD", raw)
        clean = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
        return " ".join(clean.split())

    @staticmethod
    def _humanize_core_reason(reason: str) -> str:
        token = (reason or "").strip().lower()
        labels = {
            "online": "online",
            "unreachable": "runtime_offline",
            "missing_host": "host_missing",
            "disabled": "disabled",
            "model_downloading": "model_downloading",
            "model_missing": "model_missing",
            "runtime_missing": "runtime_missing",
            "runtime_downloading": "runtime_downloading",
            "runtime_bootstrap_failed": "runtime_bootstrap_failed",
            "response_empty": "empty_response",
        }
        if token in labels:
            return labels[token]
        if token.startswith("http_"):
            return token
        return token or "unknown"
