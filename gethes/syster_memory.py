from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any


class SysterKnowledgeStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.training_db_path = self.base_dir / "syster_training.db"
        self.context_db_path = self.base_dir / "syster_context.db"
        self._lock = threading.Lock()
        self._training = sqlite3.connect(self.training_db_path, check_same_thread=False)
        self._context = sqlite3.connect(self.context_db_path, check_same_thread=False)
        self._training.row_factory = sqlite3.Row
        self._context.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            try:
                self._training.close()
            except Exception:
                pass
            try:
                self._context.close()
            except Exception:
                pass

    def _init_schema(self) -> None:
        with self._lock:
            self._training.executescript(
                """
                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    intent TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    language TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS training_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    prompt TEXT NOT NULL,
                    reply TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS long_memory (
                    memory_key TEXT PRIMARY KEY,
                    memory_value TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    source TEXT NOT NULL DEFAULT '',
                    updated_ts REAL NOT NULL
                );
                """
            )
            self._context.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS command_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    command_text TEXT NOT NULL,
                    outcome TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    slot_id INTEGER NOT NULL,
                    route_name TEXT NOT NULL,
                    stats_json TEXT NOT NULL DEFAULT '{}',
                    flags_json TEXT NOT NULL DEFAULT '{}',
                    config_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    pref_key TEXT PRIMARY KEY,
                    pref_value TEXT NOT NULL,
                    updated_ts REAL NOT NULL
                );
                """
            )
            self._training.commit()
            self._context.commit()

    def record_interaction(
        self,
        role: str,
        content: str,
        *,
        intent: str = "",
        source: str = "",
        latency_ms: int = 0,
        language: str = "",
    ) -> None:
        token = content.strip()
        if not token:
            return
        with self._lock:
            try:
                self._training.execute(
                    """
                    INSERT INTO interactions (ts, role, content, intent, source, latency_ms, language)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        time.time(),
                        role.strip() or "unknown",
                        token[:2400],
                        intent.strip()[:80],
                        source.strip()[:80],
                        int(latency_ms),
                        language.strip()[:24],
                    ),
                )
                self._training.commit()
            except Exception:
                return

    def record_feedback(self, prompt: str, reply: str, score: float, notes: str = "") -> None:
        with self._lock:
            try:
                self._training.execute(
                    """
                    INSERT INTO training_feedback (ts, prompt, reply, score, notes)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (time.time(), prompt[:2000], reply[:2000], float(score), notes[:1000]),
                )
                self._training.commit()
            except Exception:
                return

    def upsert_long_memory(
        self,
        memory_key: str,
        memory_value: str,
        *,
        weight: float = 1.0,
        source: str = "",
    ) -> None:
        key = memory_key.strip().lower()
        value = memory_value.strip()
        if not key or not value:
            return
        with self._lock:
            try:
                self._training.execute(
                    """
                    INSERT INTO long_memory (memory_key, memory_value, weight, source, updated_ts)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(memory_key) DO UPDATE SET
                        memory_value=excluded.memory_value,
                        weight=excluded.weight,
                        source=excluded.source,
                        updated_ts=excluded.updated_ts
                    """,
                    (key[:120], value[:2000], float(weight), source[:80], time.time()),
                )
                self._training.commit()
            except Exception:
                return

    def delete_long_memory(self, memory_key: str) -> bool:
        key = memory_key.strip().lower()
        if not key:
            return False
        with self._lock:
            try:
                cursor = self._training.execute(
                    "DELETE FROM long_memory WHERE memory_key = ?",
                    (key[:120],),
                )
                self._training.commit()
                return bool(cursor.rowcount)
            except Exception:
                return False

    def record_event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        event_name = event_type.strip().lower()
        if not event_name:
            return
        payload_json = "{}"
        if payload is not None:
            try:
                payload_json = json.dumps(payload, ensure_ascii=False)[:6000]
            except Exception:
                payload_json = "{}"
        with self._lock:
            try:
                self._context.execute(
                    """
                    INSERT INTO events (ts, event_type, payload)
                    VALUES (?, ?, ?)
                    """,
                    (time.time(), event_name[:80], payload_json),
                )
                self._context.commit()
            except Exception:
                return

    def record_command(self, command_text: str, outcome: str = "") -> None:
        token = command_text.strip()
        if not token:
            return
        with self._lock:
            try:
                self._context.execute(
                    """
                    INSERT INTO command_journal (ts, command_text, outcome)
                    VALUES (?, ?, ?)
                    """,
                    (time.time(), token[:320], outcome.strip()[:80]),
                )
                self._context.commit()
            except Exception:
                return

    def save_snapshot(
        self,
        *,
        slot_id: int,
        route_name: str,
        stats: dict[str, Any],
        flags: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        with self._lock:
            try:
                self._context.execute(
                    """
                    INSERT INTO snapshots (ts, slot_id, route_name, stats_json, flags_json, config_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        time.time(),
                        int(slot_id),
                        route_name.strip()[:120],
                        json.dumps(stats, ensure_ascii=False)[:14000],
                        json.dumps(flags, ensure_ascii=False)[:14000],
                        json.dumps(config, ensure_ascii=False)[:14000],
                    ),
                )
                self._context.commit()
            except Exception:
                return

    def set_preference(self, key: str, value: str) -> None:
        token = key.strip().lower()
        if not token:
            return
        with self._lock:
            try:
                self._context.execute(
                    """
                    INSERT INTO preferences (pref_key, pref_value, updated_ts)
                    VALUES (?, ?, ?)
                    ON CONFLICT(pref_key) DO UPDATE SET
                        pref_value=excluded.pref_value,
                        updated_ts=excluded.updated_ts
                    """,
                    (token[:120], value.strip()[:1000], time.time()),
                )
                self._context.commit()
            except Exception:
                return

    def get_context_digest(self, *, commands_limit: int = 6, events_limit: int = 6) -> dict[str, Any]:
        digest: dict[str, Any] = {
            "recent_commands": [],
            "recent_events": [],
            "latest_snapshot": {},
            "preferences": {},
        }
        with self._lock:
            try:
                command_rows = self._context.execute(
                    """
                    SELECT command_text FROM command_journal
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (max(1, commands_limit),),
                ).fetchall()
                digest["recent_commands"] = [str(row["command_text"]) for row in reversed(command_rows)]
            except Exception:
                pass

            try:
                event_rows = self._context.execute(
                    """
                    SELECT event_type FROM events
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (max(1, events_limit),),
                ).fetchall()
                digest["recent_events"] = [str(row["event_type"]) for row in reversed(event_rows)]
            except Exception:
                pass

            try:
                snap = self._context.execute(
                    """
                    SELECT slot_id, route_name, stats_json, flags_json, config_json
                    FROM snapshots
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).fetchone()
                if snap is not None:
                    digest["latest_snapshot"] = {
                        "slot_id": int(snap["slot_id"]),
                        "route_name": str(snap["route_name"]),
                        "stats": self._loads_safe(str(snap["stats_json"])),
                        "flags": self._loads_safe(str(snap["flags_json"])),
                        "config": self._loads_safe(str(snap["config_json"])),
                    }
            except Exception:
                pass

            try:
                pref_rows = self._context.execute(
                    """
                    SELECT pref_key, pref_value FROM preferences
                    ORDER BY pref_key ASC
                    LIMIT 40
                    """
                ).fetchall()
                digest["preferences"] = {
                    str(row["pref_key"]): str(row["pref_value"]) for row in pref_rows
                }
            except Exception:
                pass

        return digest

    def get_long_memory_entries(self, *, limit: int = 8, min_weight: float = 0.0) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        with self._lock:
            try:
                rows = self._training.execute(
                    """
                    SELECT memory_key, memory_value, weight, source, updated_ts
                    FROM long_memory
                    WHERE weight >= ?
                    ORDER BY weight DESC, updated_ts DESC
                    LIMIT ?
                    """,
                    (float(min_weight), max(1, int(limit))),
                ).fetchall()
            except Exception:
                return entries

        for row in rows:
            try:
                entries.append(
                    {
                        "key": str(row["memory_key"]),
                        "value": str(row["memory_value"]),
                        "weight": float(row["weight"]),
                        "source": str(row["source"]),
                        "updated_ts": float(row["updated_ts"]),
                    }
                )
            except Exception:
                continue
        return entries

    def get_feedback_examples(
        self,
        *,
        limit: int = 3,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        examples: list[dict[str, Any]] = []
        with self._lock:
            try:
                rows = self._training.execute(
                    """
                    SELECT prompt, reply, score, notes, ts
                    FROM training_feedback
                    WHERE score >= ?
                    ORDER BY ts DESC
                    LIMIT ?
                    """,
                    (float(min_score), max(1, int(limit))),
                ).fetchall()
            except Exception:
                return examples

        for row in rows:
            try:
                examples.append(
                    {
                        "prompt": str(row["prompt"]),
                        "reply": str(row["reply"]),
                        "score": float(row["score"]),
                        "notes": str(row["notes"]),
                        "ts": float(row["ts"]),
                    }
                )
            except Exception:
                continue
        return examples

    def get_training_overview(self) -> dict[str, int]:
        overview = {
            "interactions": 0,
            "feedback": 0,
            "long_memory": 0,
            "events": 0,
            "commands": 0,
            "snapshots": 0,
        }
        with self._lock:
            try:
                overview["interactions"] = int(
                    self._training.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
                )
            except Exception:
                pass
            try:
                overview["feedback"] = int(
                    self._training.execute("SELECT COUNT(*) FROM training_feedback").fetchone()[0]
                )
            except Exception:
                pass
            try:
                overview["long_memory"] = int(
                    self._training.execute("SELECT COUNT(*) FROM long_memory").fetchone()[0]
                )
            except Exception:
                pass
            try:
                overview["events"] = int(
                    self._context.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                )
            except Exception:
                pass
            try:
                overview["commands"] = int(
                    self._context.execute("SELECT COUNT(*) FROM command_journal").fetchone()[0]
                )
            except Exception:
                pass
            try:
                overview["snapshots"] = int(
                    self._context.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
                )
            except Exception:
                pass
        return overview

    @staticmethod
    def _loads_safe(raw: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}
