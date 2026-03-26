from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import threading
import time


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        token = value.strip()
        if token.isdigit():
            return int(token)
    return default


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        token = value.strip().replace(",", ".")
        try:
            return float(token)
        except ValueError:
            return default
    return default


def _as_bool_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if int(value) != 0 else 0
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "on", "yes"}:
            return 1
        if token in {"0", "false", "off", "no"}:
            return 0
    return default


def sanitize_name(value: str) -> str:
    merged = " ".join(value.strip().split())
    if not merged:
        return "Guest"
    cleaned = "".join(ch for ch in merged if ch.isalnum() or ch in {" ", "_", "-"})
    token = " ".join(cleaned.split()).strip()
    return (token or "Guest")[:64]


class AwsSqliteTelemetryStore:
    def __init__(self, db_path: Path, online_window_seconds: int = 120) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.online_window_seconds = max(30, int(online_window_seconds))
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS players (
                    install_id TEXT PRIMARY KEY,
                    player_name TEXT NOT NULL,
                    last_seen REAL NOT NULL,
                    version_tag TEXT,
                    slot_id INTEGER NOT NULL DEFAULT 1,
                    route_name TEXT NOT NULL DEFAULT '',
                    story_page INTEGER NOT NULL DEFAULT 0,
                    story_total INTEGER NOT NULL DEFAULT 0,
                    achievements_unlocked INTEGER NOT NULL DEFAULT 0,
                    achievements_total INTEGER NOT NULL DEFAULT 0,
                    snake_best_score INTEGER NOT NULL DEFAULT 0,
                    snake_best_level INTEGER NOT NULL DEFAULT 0,
                    snake_longest_length INTEGER NOT NULL DEFAULT 0,
                    rogue_best_depth INTEGER NOT NULL DEFAULT 0,
                    rogue_best_gold INTEGER NOT NULL DEFAULT 0,
                    rogue_best_kills INTEGER NOT NULL DEFAULT 0,
                    rogue_runs INTEGER NOT NULL DEFAULT 0,
                    rogue_wins INTEGER NOT NULL DEFAULT 0,
                    graphics_mode TEXT NOT NULL DEFAULT '',
                    language_active TEXT NOT NULL DEFAULT '',
                    ui_scale REAL NOT NULL DEFAULT 1.0,
                    theme_name TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_players_last_seen ON players(last_seen);

                CREATE TABLE IF NOT EXISTS syster_profile (
                    install_id TEXT PRIMARY KEY,
                    player_name TEXT NOT NULL,
                    last_sync REAL NOT NULL,
                    mode_tag TEXT,
                    core_enabled INTEGER NOT NULL DEFAULT 0,
                    model_tag TEXT,
                    interactions_count INTEGER NOT NULL DEFAULT 0,
                    feedback_count INTEGER NOT NULL DEFAULT 0,
                    long_memory_count INTEGER NOT NULL DEFAULT 0,
                    events_count INTEGER NOT NULL DEFAULT 0,
                    commands_count INTEGER NOT NULL DEFAULT 0,
                    snapshots_count INTEGER NOT NULL DEFAULT 0,
                    feedback_avg_score REAL NOT NULL DEFAULT 0.0,
                    feedback_positive INTEGER NOT NULL DEFAULT 0,
                    feedback_negative INTEGER NOT NULL DEFAULT 0,
                    memory_top_json TEXT NOT NULL DEFAULT '[]',
                    intent_top_json TEXT NOT NULL DEFAULT '[]',
                    training_meta_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS syster_feedback (
                    install_id TEXT NOT NULL,
                    sample_local_id INTEGER NOT NULL,
                    player_name TEXT NOT NULL,
                    sample_ts REAL NOT NULL,
                    score_value REAL NOT NULL DEFAULT 0.0,
                    notes_text TEXT NOT NULL DEFAULT '',
                    prompt_text TEXT NOT NULL DEFAULT '',
                    reply_text TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (install_id, sample_local_id)
                );
                """
            )
            self._conn.commit()

    @staticmethod
    def _compact(value: object, limit: int) -> str:
        token = " ".join(str(value or "").split()).strip()
        if len(token) <= limit:
            return token
        return token[:limit].rstrip()

    @staticmethod
    def _compact_json(value: object, limit: int = 3500) -> str:
        try:
            raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            raw = "{}"
        if len(raw) <= limit:
            return raw
        return raw[:limit].rstrip()

    def _upsert_player(self, payload: dict[str, object]) -> str:
        install_id = str(payload.get("install_id", "")).strip().lower().replace("-", "")[:64]
        if not install_id:
            raise ValueError("missing_install_id")

        player_name = sanitize_name(str(payload.get("player_name", "Guest")))
        version_tag = self._compact(payload.get("version", ""), 32)
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        scores = payload.get("scores") if isinstance(payload.get("scores"), dict) else {}
        prefs = payload.get("preferences") if isinstance(payload.get("preferences"), dict) else {}
        now_ts = time.time()

        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM players WHERE install_id = ?",
                (install_id,),
            ).fetchone()
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO players (
                        install_id, player_name, last_seen, version_tag, slot_id, route_name,
                        story_page, story_total, achievements_unlocked, achievements_total,
                        snake_best_score, snake_best_level, snake_longest_length,
                        rogue_best_depth, rogue_best_gold, rogue_best_kills, rogue_runs, rogue_wins,
                        graphics_mode, language_active, ui_scale, theme_name, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        install_id,
                        player_name,
                        now_ts,
                        version_tag,
                        _as_int(profile.get("slot_id"), 1),
                        self._compact(profile.get("route_name", ""), 128),
                        _as_int(profile.get("story_page")),
                        _as_int(profile.get("story_total")),
                        _as_int(profile.get("achievements_unlocked")),
                        _as_int(profile.get("achievements_total")),
                        _as_int(scores.get("snake_best_score")),
                        _as_int(scores.get("snake_best_level")),
                        _as_int(scores.get("snake_longest_length")),
                        _as_int(scores.get("rogue_best_depth")),
                        _as_int(scores.get("rogue_best_gold")),
                        _as_int(scores.get("rogue_best_kills")),
                        _as_int(scores.get("rogue_runs")),
                        _as_int(scores.get("rogue_wins")),
                        self._compact(prefs.get("graphics", ""), 16),
                        self._compact(prefs.get("language_active", ""), 8),
                        round(_as_float(prefs.get("ui_scale"), 1.0), 2),
                        self._compact(prefs.get("theme", ""), 64),
                        now_ts,
                    ),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE players SET
                        player_name = ?,
                        last_seen = ?,
                        version_tag = ?,
                        slot_id = ?,
                        route_name = ?,
                        story_page = ?,
                        story_total = ?,
                        achievements_unlocked = ?,
                        achievements_total = ?,
                        snake_best_score = MAX(snake_best_score, ?),
                        snake_best_level = MAX(snake_best_level, ?),
                        snake_longest_length = MAX(snake_longest_length, ?),
                        rogue_best_depth = MAX(rogue_best_depth, ?),
                        rogue_best_gold = MAX(rogue_best_gold, ?),
                        rogue_best_kills = MAX(rogue_best_kills, ?),
                        rogue_runs = MAX(rogue_runs, ?),
                        rogue_wins = MAX(rogue_wins, ?),
                        graphics_mode = ?,
                        language_active = ?,
                        ui_scale = ?,
                        theme_name = ?,
                        updated_at = ?
                    WHERE install_id = ?
                    """,
                    (
                        player_name,
                        now_ts,
                        version_tag,
                        _as_int(profile.get("slot_id"), 1),
                        self._compact(profile.get("route_name", ""), 128),
                        _as_int(profile.get("story_page")),
                        _as_int(profile.get("story_total")),
                        _as_int(profile.get("achievements_unlocked")),
                        _as_int(profile.get("achievements_total")),
                        _as_int(scores.get("snake_best_score")),
                        _as_int(scores.get("snake_best_level")),
                        _as_int(scores.get("snake_longest_length")),
                        _as_int(scores.get("rogue_best_depth")),
                        _as_int(scores.get("rogue_best_gold")),
                        _as_int(scores.get("rogue_best_kills")),
                        _as_int(scores.get("rogue_runs")),
                        _as_int(scores.get("rogue_wins")),
                        self._compact(prefs.get("graphics", ""), 16),
                        self._compact(prefs.get("language_active", ""), 8),
                        round(_as_float(prefs.get("ui_scale"), 1.0), 2),
                        self._compact(prefs.get("theme", ""), 64),
                        now_ts,
                        install_id,
                    ),
                )
            self._conn.commit()
        return install_id

    def _upsert_syster(self, payload: dict[str, object], install_id: str, player_name: str) -> int:
        syster_payload = payload.get("syster") if isinstance(payload.get("syster"), dict) else {}
        if not syster_payload:
            return 0

        training = (
            syster_payload.get("training")
            if isinstance(syster_payload.get("training"), dict)
            else {}
        )
        overview = training.get("overview") if isinstance(training.get("overview"), dict) else {}
        memory_top = training.get("memory_top") if isinstance(training.get("memory_top"), list) else []
        intent_top = training.get("intent_top") if isinstance(training.get("intent_top"), list) else []
        samples = (
            training.get("feedback_samples")
            if isinstance(training.get("feedback_samples"), list)
            else []
        )
        now_ts = time.time()

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO syster_profile (
                    install_id, player_name, last_sync, mode_tag, core_enabled, model_tag,
                    interactions_count, feedback_count, long_memory_count, events_count, commands_count, snapshots_count,
                    feedback_avg_score, feedback_positive, feedback_negative,
                    memory_top_json, intent_top_json, training_meta_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(install_id) DO UPDATE SET
                    player_name=excluded.player_name,
                    last_sync=excluded.last_sync,
                    mode_tag=excluded.mode_tag,
                    core_enabled=excluded.core_enabled,
                    model_tag=excluded.model_tag,
                    interactions_count=MAX(syster_profile.interactions_count, excluded.interactions_count),
                    feedback_count=MAX(syster_profile.feedback_count, excluded.feedback_count),
                    long_memory_count=MAX(syster_profile.long_memory_count, excluded.long_memory_count),
                    events_count=MAX(syster_profile.events_count, excluded.events_count),
                    commands_count=MAX(syster_profile.commands_count, excluded.commands_count),
                    snapshots_count=MAX(syster_profile.snapshots_count, excluded.snapshots_count),
                    feedback_avg_score=excluded.feedback_avg_score,
                    feedback_positive=MAX(syster_profile.feedback_positive, excluded.feedback_positive),
                    feedback_negative=MAX(syster_profile.feedback_negative, excluded.feedback_negative),
                    memory_top_json=excluded.memory_top_json,
                    intent_top_json=excluded.intent_top_json,
                    training_meta_json=excluded.training_meta_json,
                    updated_at=excluded.updated_at
                """,
                (
                    install_id,
                    player_name,
                    now_ts,
                    self._compact(syster_payload.get("mode", ""), 24),
                    _as_bool_int(syster_payload.get("core_enabled"), 0),
                    self._compact(syster_payload.get("model", ""), 128),
                    _as_int(overview.get("interactions")),
                    _as_int(overview.get("feedback")),
                    _as_int(overview.get("long_memory")),
                    _as_int(overview.get("events")),
                    _as_int(overview.get("commands")),
                    _as_int(overview.get("snapshots")),
                    round(_as_float(training.get("feedback_avg_score"), 0.0), 4),
                    _as_int(training.get("feedback_positive")),
                    _as_int(training.get("feedback_negative")),
                    self._compact_json(memory_top[:8]),
                    self._compact_json(intent_top[:8]),
                    self._compact_json(
                        {
                            "updated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "mode": self._compact(syster_payload.get("mode", ""), 24),
                            "model": self._compact(syster_payload.get("model", ""), 128),
                        }
                    ),
                    now_ts,
                ),
            )

            ingested = 0
            for item in samples[:20]:
                if not isinstance(item, dict):
                    continue
                local_id = _as_int(item.get("local_id"), 0)
                if local_id <= 0:
                    continue
                self._conn.execute(
                    """
                    INSERT INTO syster_feedback (
                        install_id, sample_local_id, player_name, sample_ts,
                        score_value, notes_text, prompt_text, reply_text, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(install_id, sample_local_id) DO UPDATE SET
                        player_name=excluded.player_name,
                        sample_ts=excluded.sample_ts,
                        score_value=excluded.score_value,
                        notes_text=excluded.notes_text,
                        prompt_text=excluded.prompt_text,
                        reply_text=excluded.reply_text,
                        updated_at=excluded.updated_at
                    """,
                    (
                        install_id,
                        local_id,
                        player_name,
                        _as_float(item.get("ts"), now_ts),
                        round(_as_float(item.get("score"), 0.0), 4),
                        self._compact(item.get("notes", ""), 500),
                        self._compact(item.get("prompt", ""), 1000),
                        self._compact(item.get("reply", ""), 1000),
                        now_ts,
                    ),
                )
                ingested += 1
            self._conn.commit()
        return ingested

    def syster_global_summary(self) -> dict[str, object]:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c, COALESCE(AVG(score_value), 0.0) AS avg_score FROM syster_feedback"
            ).fetchone()
        if row is None:
            return {"samples": 0, "avg_score": 0.0}
        return {"samples": _as_int(row["c"]), "avg_score": round(_as_float(row["avg_score"]), 4)}

    def presence(self) -> tuple[int, int]:
        threshold = time.time() - float(self.online_window_seconds)
        with self._lock:
            row_online = self._conn.execute(
                "SELECT COUNT(*) AS c FROM players WHERE last_seen >= ?",
                (threshold,),
            ).fetchone()
            row_total = self._conn.execute("SELECT COUNT(*) AS c FROM players").fetchone()
        online = _as_int(row_online["c"]) if row_online is not None else 0
        total = _as_int(row_total["c"]) if row_total is not None else 0
        return online, total

    def heartbeat(self, payload: dict[str, object]) -> dict[str, object]:
        install_id = self._upsert_player(payload)
        player_name = sanitize_name(str(payload.get("player_name", "Guest")))
        ingested = self._upsert_syster(payload, install_id, player_name)
        online, users = self.presence()
        syster = self.syster_global_summary()
        return {
            "ok": True,
            "message": "synced",
            "players_online": online,
            "registered_users": users,
            "syster_profile_synced": bool(isinstance(payload.get("syster"), dict)),
            "syster_feedback_ingested": int(ingested),
            "syster_global_samples": int(syster.get("samples", 0) or 0),
            "syster_global_avg_score": float(syster.get("avg_score", 0.0) or 0.0),
            "server_time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


class TelemetryHandler(BaseHTTPRequestHandler):
    store: AwsSqliteTelemetryStore | None = None
    api_key: str = ""

    def do_GET(self) -> None:  # pragma: no cover
        if self.path.startswith("/health"):
            self._send_json(HTTPStatus.OK, {"ok": True, "service": "aws_sqlite_cloud"})
            return
        if self.path.startswith("/v1/telemetry/presence"):
            if not self._authorize():
                return
            if self.store is None:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "message": "store_unavailable"})
                return
            online, users = self.store.presence()
            syster = self.store.syster_global_summary()
            self._send_json(
                HTTPStatus.OK,
                {
                    "players_online": online,
                    "registered_users": users,
                    "syster_global_samples": int(syster.get("samples", 0) or 0),
                    "syster_global_avg_score": float(syster.get("avg_score", 0.0) or 0.0),
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "not_found"})

    def do_POST(self) -> None:  # pragma: no cover
        if self.path != "/v1/telemetry/heartbeat":
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "not_found"})
            return
        if not self._authorize():
            return
        if self.store is None:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "message": "store_unavailable"})
            return

        raw_length = self.headers.get("Content-Length", "").strip()
        if not raw_length.isdigit():
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "missing_content_length"})
            return
        raw = self.rfile.read(int(raw_length))
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "invalid_json"})
            return
        if not isinstance(payload, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "invalid_payload"})
            return

        try:
            data = self.store.heartbeat(payload)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": str(exc)})
            return
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "message": str(exc)})
            return
        self._send_json(HTTPStatus.OK, data)

    def _authorize(self) -> bool:
        if not self.api_key:
            return True
        incoming = self.headers.get("X-API-Key", "").strip()
        if not incoming:
            auth = self.headers.get("Authorization", "").strip()
            if auth.lower().startswith("bearer "):
                incoming = auth[7:].strip()
        if incoming == self.api_key:
            return True
        self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "message": "unauthorized"})
        return False

    def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: object) -> None:
        return


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gethes AWS-native telemetry backend (SQLite)")
    parser.add_argument("--db-path", type=Path, default=Path("gethes_telemetry.db"), help="SQLite DB path")
    parser.add_argument("--api-key", default="", help="Optional API key for heartbeat/presence")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host")
    parser.add_argument("--port", type=int, default=8787, help="HTTP bind port")
    parser.add_argument("--online-window-seconds", type=int, default=120, help="Presence window")
    return parser


def main() -> None:  # pragma: no cover
    parser = build_arg_parser()
    args = parser.parse_args()

    store = AwsSqliteTelemetryStore(
        db_path=args.db_path,
        online_window_seconds=args.online_window_seconds,
    )
    TelemetryHandler.store = store
    TelemetryHandler.api_key = args.api_key.strip()
    server = ThreadingHTTPServer((args.host, int(args.port)), TelemetryHandler)
    print(f"[aws] Backend ready on http://{args.host}:{args.port}")
    print(f"[aws] SQLite DB: {args.db_path}")
    if TelemetryHandler.api_key:
        print("[aws] API key auth: enabled")
    else:
        print("[aws] API key auth: disabled")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[aws] Shutting down...")
    finally:
        server.server_close()
        store.close()


if __name__ == "__main__":
    main()
