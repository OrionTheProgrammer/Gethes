from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import zipfile

try:
    import oracledb
except ImportError as exc:  # pragma: no cover - runtime dependency
    raise SystemExit(
        "Missing dependency `oracledb`. Install with: pip install oracledb"
    ) from exc


CREATE_TABLE_SQL = """
CREATE TABLE GETHES_TELEMETRY_PLAYERS (
    INSTALL_ID VARCHAR2(64) PRIMARY KEY,
    PLAYER_NAME VARCHAR2(128) NOT NULL,
    LAST_SEEN TIMESTAMP WITH TIME ZONE NOT NULL,
    VERSION_TAG VARCHAR2(32),
    SLOT_ID NUMBER(3),
    ROUTE_NAME VARCHAR2(128),
    STORY_PAGE NUMBER(8),
    STORY_TOTAL NUMBER(8),
    ACHIEVEMENTS_UNLOCKED NUMBER(8),
    ACHIEVEMENTS_TOTAL NUMBER(8),
    SNAKE_BEST_SCORE NUMBER(12),
    SNAKE_BEST_LEVEL NUMBER(8),
    SNAKE_LONGEST_LENGTH NUMBER(8),
    ROGUE_BEST_DEPTH NUMBER(8),
    ROGUE_BEST_GOLD NUMBER(12),
    ROGUE_BEST_KILLS NUMBER(12),
    ROGUE_RUNS NUMBER(12),
    ROGUE_WINS NUMBER(12),
    GRAPHICS_MODE VARCHAR2(16),
    LANGUAGE_ACTIVE VARCHAR2(8),
    UI_SCALE NUMBER(6,2),
    THEME_NAME VARCHAR2(64),
    UPDATED_AT TIMESTAMP WITH TIME ZONE NOT NULL
)
"""

MERGE_SQL = """
MERGE INTO GETHES_TELEMETRY_PLAYERS t
USING (
    SELECT
        :install_id AS INSTALL_ID,
        :player_name AS PLAYER_NAME,
        SYSTIMESTAMP AS LAST_SEEN,
        :version_tag AS VERSION_TAG,
        :slot_id AS SLOT_ID,
        :route_name AS ROUTE_NAME,
        :story_page AS STORY_PAGE,
        :story_total AS STORY_TOTAL,
        :achievements_unlocked AS ACHIEVEMENTS_UNLOCKED,
        :achievements_total AS ACHIEVEMENTS_TOTAL,
        :snake_best_score AS SNAKE_BEST_SCORE,
        :snake_best_level AS SNAKE_BEST_LEVEL,
        :snake_longest_length AS SNAKE_LONGEST_LENGTH,
        :rogue_best_depth AS ROGUE_BEST_DEPTH,
        :rogue_best_gold AS ROGUE_BEST_GOLD,
        :rogue_best_kills AS ROGUE_BEST_KILLS,
        :rogue_runs AS ROGUE_RUNS,
        :rogue_wins AS ROGUE_WINS,
        :graphics_mode AS GRAPHICS_MODE,
        :language_active AS LANGUAGE_ACTIVE,
        :ui_scale AS UI_SCALE,
        :theme_name AS THEME_NAME
    FROM dual
) s
ON (t.INSTALL_ID = s.INSTALL_ID)
WHEN MATCHED THEN
    UPDATE SET
        t.PLAYER_NAME = s.PLAYER_NAME,
        t.LAST_SEEN = s.LAST_SEEN,
        t.VERSION_TAG = s.VERSION_TAG,
        t.SLOT_ID = s.SLOT_ID,
        t.ROUTE_NAME = s.ROUTE_NAME,
        t.STORY_PAGE = s.STORY_PAGE,
        t.STORY_TOTAL = s.STORY_TOTAL,
        t.ACHIEVEMENTS_UNLOCKED = s.ACHIEVEMENTS_UNLOCKED,
        t.ACHIEVEMENTS_TOTAL = s.ACHIEVEMENTS_TOTAL,
        t.SNAKE_BEST_SCORE = GREATEST(NVL(t.SNAKE_BEST_SCORE, 0), NVL(s.SNAKE_BEST_SCORE, 0)),
        t.SNAKE_BEST_LEVEL = GREATEST(NVL(t.SNAKE_BEST_LEVEL, 0), NVL(s.SNAKE_BEST_LEVEL, 0)),
        t.SNAKE_LONGEST_LENGTH = GREATEST(NVL(t.SNAKE_LONGEST_LENGTH, 0), NVL(s.SNAKE_LONGEST_LENGTH, 0)),
        t.ROGUE_BEST_DEPTH = GREATEST(NVL(t.ROGUE_BEST_DEPTH, 0), NVL(s.ROGUE_BEST_DEPTH, 0)),
        t.ROGUE_BEST_GOLD = GREATEST(NVL(t.ROGUE_BEST_GOLD, 0), NVL(s.ROGUE_BEST_GOLD, 0)),
        t.ROGUE_BEST_KILLS = GREATEST(NVL(t.ROGUE_BEST_KILLS, 0), NVL(s.ROGUE_BEST_KILLS, 0)),
        t.ROGUE_RUNS = GREATEST(NVL(t.ROGUE_RUNS, 0), NVL(s.ROGUE_RUNS, 0)),
        t.ROGUE_WINS = GREATEST(NVL(t.ROGUE_WINS, 0), NVL(s.ROGUE_WINS, 0)),
        t.GRAPHICS_MODE = s.GRAPHICS_MODE,
        t.LANGUAGE_ACTIVE = s.LANGUAGE_ACTIVE,
        t.UI_SCALE = s.UI_SCALE,
        t.THEME_NAME = s.THEME_NAME,
        t.UPDATED_AT = SYSTIMESTAMP
WHEN NOT MATCHED THEN
    INSERT (
        INSTALL_ID,
        PLAYER_NAME,
        LAST_SEEN,
        VERSION_TAG,
        SLOT_ID,
        ROUTE_NAME,
        STORY_PAGE,
        STORY_TOTAL,
        ACHIEVEMENTS_UNLOCKED,
        ACHIEVEMENTS_TOTAL,
        SNAKE_BEST_SCORE,
        SNAKE_BEST_LEVEL,
        SNAKE_LONGEST_LENGTH,
        ROGUE_BEST_DEPTH,
        ROGUE_BEST_GOLD,
        ROGUE_BEST_KILLS,
        ROGUE_RUNS,
        ROGUE_WINS,
        GRAPHICS_MODE,
        LANGUAGE_ACTIVE,
        UI_SCALE,
        THEME_NAME,
        UPDATED_AT
    )
    VALUES (
        s.INSTALL_ID,
        s.PLAYER_NAME,
        s.LAST_SEEN,
        s.VERSION_TAG,
        s.SLOT_ID,
        s.ROUTE_NAME,
        s.STORY_PAGE,
        s.STORY_TOTAL,
        s.ACHIEVEMENTS_UNLOCKED,
        s.ACHIEVEMENTS_TOTAL,
        s.SNAKE_BEST_SCORE,
        s.SNAKE_BEST_LEVEL,
        s.SNAKE_LONGEST_LENGTH,
        s.ROGUE_BEST_DEPTH,
        s.ROGUE_BEST_GOLD,
        s.ROGUE_BEST_KILLS,
        s.ROGUE_RUNS,
        s.ROGUE_WINS,
        s.GRAPHICS_MODE,
        s.LANGUAGE_ACTIVE,
        s.UI_SCALE,
        s.THEME_NAME,
        SYSTIMESTAMP
    )
"""

CREATE_SYSTER_PROFILE_TABLE_SQL = """
CREATE TABLE GETHES_SYSTER_PROFILE (
    INSTALL_ID VARCHAR2(64) PRIMARY KEY,
    PLAYER_NAME VARCHAR2(128) NOT NULL,
    LAST_SYNC TIMESTAMP WITH TIME ZONE NOT NULL,
    MODE_TAG VARCHAR2(24),
    CORE_ENABLED NUMBER(1) DEFAULT 0,
    MODEL_TAG VARCHAR2(128),
    INTERACTIONS_COUNT NUMBER(18),
    FEEDBACK_COUNT NUMBER(18),
    LONG_MEMORY_COUNT NUMBER(18),
    EVENTS_COUNT NUMBER(18),
    COMMANDS_COUNT NUMBER(18),
    SNAPSHOTS_COUNT NUMBER(18),
    FEEDBACK_AVG_SCORE NUMBER(8,4),
    FEEDBACK_POSITIVE NUMBER(18),
    FEEDBACK_NEGATIVE NUMBER(18),
    MEMORY_TOP_JSON VARCHAR2(3900),
    INTENT_TOP_JSON VARCHAR2(3900),
    TRAINING_META_JSON VARCHAR2(3900),
    UPDATED_AT TIMESTAMP WITH TIME ZONE NOT NULL
)
"""

MERGE_SYSTER_PROFILE_SQL = """
MERGE INTO GETHES_SYSTER_PROFILE t
USING (
    SELECT
        :install_id AS INSTALL_ID,
        :player_name AS PLAYER_NAME,
        SYSTIMESTAMP AS LAST_SYNC,
        :mode_tag AS MODE_TAG,
        :core_enabled AS CORE_ENABLED,
        :model_tag AS MODEL_TAG,
        :interactions_count AS INTERACTIONS_COUNT,
        :feedback_count AS FEEDBACK_COUNT,
        :long_memory_count AS LONG_MEMORY_COUNT,
        :events_count AS EVENTS_COUNT,
        :commands_count AS COMMANDS_COUNT,
        :snapshots_count AS SNAPSHOTS_COUNT,
        :feedback_avg_score AS FEEDBACK_AVG_SCORE,
        :feedback_positive AS FEEDBACK_POSITIVE,
        :feedback_negative AS FEEDBACK_NEGATIVE,
        :memory_top_json AS MEMORY_TOP_JSON,
        :intent_top_json AS INTENT_TOP_JSON,
        :training_meta_json AS TRAINING_META_JSON
    FROM dual
) s
ON (t.INSTALL_ID = s.INSTALL_ID)
WHEN MATCHED THEN
    UPDATE SET
        t.PLAYER_NAME = s.PLAYER_NAME,
        t.LAST_SYNC = s.LAST_SYNC,
        t.MODE_TAG = s.MODE_TAG,
        t.CORE_ENABLED = s.CORE_ENABLED,
        t.MODEL_TAG = s.MODEL_TAG,
        t.INTERACTIONS_COUNT = GREATEST(NVL(t.INTERACTIONS_COUNT, 0), NVL(s.INTERACTIONS_COUNT, 0)),
        t.FEEDBACK_COUNT = GREATEST(NVL(t.FEEDBACK_COUNT, 0), NVL(s.FEEDBACK_COUNT, 0)),
        t.LONG_MEMORY_COUNT = GREATEST(NVL(t.LONG_MEMORY_COUNT, 0), NVL(s.LONG_MEMORY_COUNT, 0)),
        t.EVENTS_COUNT = GREATEST(NVL(t.EVENTS_COUNT, 0), NVL(s.EVENTS_COUNT, 0)),
        t.COMMANDS_COUNT = GREATEST(NVL(t.COMMANDS_COUNT, 0), NVL(s.COMMANDS_COUNT, 0)),
        t.SNAPSHOTS_COUNT = GREATEST(NVL(t.SNAPSHOTS_COUNT, 0), NVL(s.SNAPSHOTS_COUNT, 0)),
        t.FEEDBACK_AVG_SCORE = s.FEEDBACK_AVG_SCORE,
        t.FEEDBACK_POSITIVE = GREATEST(NVL(t.FEEDBACK_POSITIVE, 0), NVL(s.FEEDBACK_POSITIVE, 0)),
        t.FEEDBACK_NEGATIVE = GREATEST(NVL(t.FEEDBACK_NEGATIVE, 0), NVL(s.FEEDBACK_NEGATIVE, 0)),
        t.MEMORY_TOP_JSON = s.MEMORY_TOP_JSON,
        t.INTENT_TOP_JSON = s.INTENT_TOP_JSON,
        t.TRAINING_META_JSON = s.TRAINING_META_JSON,
        t.UPDATED_AT = SYSTIMESTAMP
WHEN NOT MATCHED THEN
    INSERT (
        INSTALL_ID,
        PLAYER_NAME,
        LAST_SYNC,
        MODE_TAG,
        CORE_ENABLED,
        MODEL_TAG,
        INTERACTIONS_COUNT,
        FEEDBACK_COUNT,
        LONG_MEMORY_COUNT,
        EVENTS_COUNT,
        COMMANDS_COUNT,
        SNAPSHOTS_COUNT,
        FEEDBACK_AVG_SCORE,
        FEEDBACK_POSITIVE,
        FEEDBACK_NEGATIVE,
        MEMORY_TOP_JSON,
        INTENT_TOP_JSON,
        TRAINING_META_JSON,
        UPDATED_AT
    )
    VALUES (
        s.INSTALL_ID,
        s.PLAYER_NAME,
        s.LAST_SYNC,
        s.MODE_TAG,
        s.CORE_ENABLED,
        s.MODEL_TAG,
        s.INTERACTIONS_COUNT,
        s.FEEDBACK_COUNT,
        s.LONG_MEMORY_COUNT,
        s.EVENTS_COUNT,
        s.COMMANDS_COUNT,
        s.SNAPSHOTS_COUNT,
        s.FEEDBACK_AVG_SCORE,
        s.FEEDBACK_POSITIVE,
        s.FEEDBACK_NEGATIVE,
        s.MEMORY_TOP_JSON,
        s.INTENT_TOP_JSON,
        s.TRAINING_META_JSON,
        SYSTIMESTAMP
    )
"""

CREATE_SYSTER_FEEDBACK_TABLE_SQL = """
CREATE TABLE GETHES_SYSTER_FEEDBACK (
    INSTALL_ID VARCHAR2(64) NOT NULL,
    SAMPLE_LOCAL_ID NUMBER(18) NOT NULL,
    PLAYER_NAME VARCHAR2(128) NOT NULL,
    SAMPLE_TS TIMESTAMP WITH TIME ZONE NOT NULL,
    SCORE_VALUE NUMBER(8,4),
    NOTES_TEXT VARCHAR2(500),
    PROMPT_TEXT VARCHAR2(1000),
    REPLY_TEXT VARCHAR2(1000),
    UPDATED_AT TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT GETHES_SYSTER_FEEDBACK_PK PRIMARY KEY (INSTALL_ID, SAMPLE_LOCAL_ID)
)
"""

MERGE_SYSTER_FEEDBACK_SQL = """
MERGE INTO GETHES_SYSTER_FEEDBACK t
USING (
    SELECT
        :install_id AS INSTALL_ID,
        :sample_local_id AS SAMPLE_LOCAL_ID,
        :player_name AS PLAYER_NAME,
        :sample_ts AS SAMPLE_TS,
        :score_value AS SCORE_VALUE,
        :notes_text AS NOTES_TEXT,
        :prompt_text AS PROMPT_TEXT,
        :reply_text AS REPLY_TEXT
    FROM dual
) s
ON (t.INSTALL_ID = s.INSTALL_ID AND t.SAMPLE_LOCAL_ID = s.SAMPLE_LOCAL_ID)
WHEN MATCHED THEN
    UPDATE SET
        t.PLAYER_NAME = s.PLAYER_NAME,
        t.SAMPLE_TS = s.SAMPLE_TS,
        t.SCORE_VALUE = s.SCORE_VALUE,
        t.NOTES_TEXT = s.NOTES_TEXT,
        t.PROMPT_TEXT = s.PROMPT_TEXT,
        t.REPLY_TEXT = s.REPLY_TEXT,
        t.UPDATED_AT = SYSTIMESTAMP
WHEN NOT MATCHED THEN
    INSERT (
        INSTALL_ID,
        SAMPLE_LOCAL_ID,
        PLAYER_NAME,
        SAMPLE_TS,
        SCORE_VALUE,
        NOTES_TEXT,
        PROMPT_TEXT,
        REPLY_TEXT,
        UPDATED_AT
    )
    VALUES (
        s.INSTALL_ID,
        s.SAMPLE_LOCAL_ID,
        s.PLAYER_NAME,
        s.SAMPLE_TS,
        s.SCORE_VALUE,
        s.NOTES_TEXT,
        s.PROMPT_TEXT,
        s.REPLY_TEXT,
        SYSTIMESTAMP
    )
"""


def sanitize_name(value: str) -> str:
    merged = " ".join(value.strip().split())
    if not merged:
        return "Guest"
    cleaned = "".join(ch for ch in merged if ch.isalnum() or ch in {" ", "_", "-"})
    clean = " ".join(cleaned.split()).strip()
    return (clean or "Guest")[:64]


def parse_tns_aliases(text: str) -> list[str]:
    aliases: list[str] = []
    pattern = re.compile(r"^\s*([A-Za-z0-9_.$#-]+)\s*=", re.IGNORECASE)
    for line in text.splitlines():
        line_strip = line.strip()
        if not line_strip or line_strip.startswith("#"):
            continue
        hit = pattern.match(line_strip)
        if not hit:
            continue
        alias = hit.group(1).strip()
        if alias and alias not in aliases:
            aliases.append(alias)
    return aliases


def extract_wallet(zip_path: Path, target_dir: Path) -> tuple[Path, list[str]]:
    if not zip_path.exists():
        raise FileNotFoundError(f"Wallet zip not found: {zip_path}")

    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(target_dir)

    tns = target_dir / "tnsnames.ora"
    if not tns.exists():
        raise FileNotFoundError("tnsnames.ora not found in extracted wallet")
    aliases = parse_tns_aliases(tns.read_text(encoding="utf-8", errors="ignore"))
    return target_dir, aliases


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _as_float(value: object, default: float = 1.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _as_bool_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if int(value) != 0 else 0
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return 1
        if token in {"0", "false", "no", "off"}:
            return 0
    return default


class OracleTelemetryStore:
    def __init__(
        self,
        wallet_dir: Path,
        dsn: str,
        db_user: str,
        db_password: str,
        wallet_password: str = "",
        online_window_seconds: int = 120,
        tcp_connect_timeout: float = 6.0,
        retry_count: int = 1,
        retry_delay: int = 1,
    ) -> None:
        self.wallet_dir = wallet_dir
        self.dsn = dsn
        self.db_user = db_user
        self.db_password = db_password
        self.wallet_password = wallet_password
        self.online_window_seconds = max(30, int(online_window_seconds))
        self.tcp_connect_timeout = max(1.0, float(tcp_connect_timeout))
        self.retry_count = max(0, int(retry_count))
        self.retry_delay = max(0, int(retry_delay))
        self.pool = self._create_pool()
        self._ensure_schema()

    def _create_pool(self) -> "oracledb.ConnectionPool":
        kwargs: dict[str, object] = {
            "user": self.db_user,
            "password": self.db_password,
            "dsn": self.dsn,
            "config_dir": str(self.wallet_dir),
            "wallet_location": str(self.wallet_dir),
            "tcp_connect_timeout": self.tcp_connect_timeout,
            "retry_count": self.retry_count,
            "retry_delay": self.retry_delay,
            "min": 1,
            "max": 6,
            "increment": 1,
            "stmtcachesize": 40,
        }
        if self.wallet_password:
            kwargs["wallet_password"] = self.wallet_password
        return oracledb.create_pool(**kwargs)

    @staticmethod
    def _oracle_code(exc: Exception) -> int:
        args = getattr(exc, "args", ())
        if not args:
            return 0
        first = args[0]
        code = getattr(first, "code", 0)
        if isinstance(code, int):
            return code
        return 0

    def _execute_ddl(self, cursor: "oracledb.Cursor", sql: str) -> None:
        try:
            cursor.execute(sql)
        except Exception as exc:
            if self._oracle_code(exc) == 955:
                return
            raise

    def _ensure_schema(self) -> None:
        with self.pool.acquire() as conn:
            with conn.cursor() as cur:
                self._execute_ddl(cur, CREATE_TABLE_SQL)
                self._execute_ddl(cur, CREATE_SYSTER_PROFILE_TABLE_SQL)
                self._execute_ddl(cur, CREATE_SYSTER_FEEDBACK_TABLE_SQL)
            conn.commit()

    @staticmethod
    def _compact_text(value: object, limit: int) -> str:
        merged = " ".join(str(value or "").split()).strip()
        if len(merged) <= limit:
            return merged
        return merged[:limit].rstrip()

    def _compact_json(self, value: object, limit: int = 3900) -> str:
        try:
            raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            raw = "{}"
        return self._compact_text(raw, limit)

    def _upsert_syster_profile(
        self,
        cursor: "oracledb.Cursor",
        *,
        install_id: str,
        player_name: str,
        syster_payload: dict[str, object],
    ) -> bool:
        training = (
            syster_payload.get("training")
            if isinstance(syster_payload.get("training"), dict)
            else {}
        )
        overview = (
            training.get("overview")
            if isinstance(training.get("overview"), dict)
            else {}
        )
        memory_top = (
            training.get("memory_top")
            if isinstance(training.get("memory_top"), list)
            else []
        )
        intent_top = (
            training.get("intent_top")
            if isinstance(training.get("intent_top"), list)
            else []
        )
        binds = {
            "install_id": install_id,
            "player_name": player_name,
            "mode_tag": self._compact_text(syster_payload.get("mode", ""), 24),
            "core_enabled": _as_bool_int(syster_payload.get("core_enabled"), 0),
            "model_tag": self._compact_text(syster_payload.get("model", ""), 128),
            "interactions_count": _as_int(overview.get("interactions")),
            "feedback_count": _as_int(overview.get("feedback")),
            "long_memory_count": _as_int(overview.get("long_memory")),
            "events_count": _as_int(overview.get("events")),
            "commands_count": _as_int(overview.get("commands")),
            "snapshots_count": _as_int(overview.get("snapshots")),
            "feedback_avg_score": round(_as_float(training.get("feedback_avg_score"), 0.0), 4),
            "feedback_positive": _as_int(training.get("feedback_positive")),
            "feedback_negative": _as_int(training.get("feedback_negative")),
            "memory_top_json": self._compact_json(memory_top[:8], 3900),
            "intent_top_json": self._compact_json(intent_top[:8], 3900),
            "training_meta_json": self._compact_json(
                {
                    "updated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "mode": syster_payload.get("mode", ""),
                    "model": syster_payload.get("model", ""),
                    "feedback_avg_score": round(_as_float(training.get("feedback_avg_score"), 0.0), 4),
                    "feedback_positive": _as_int(training.get("feedback_positive")),
                    "feedback_negative": _as_int(training.get("feedback_negative")),
                },
                3900,
            ),
        }
        cursor.execute(MERGE_SYSTER_PROFILE_SQL, binds)
        return True

    def _upsert_syster_feedback_samples(
        self,
        cursor: "oracledb.Cursor",
        *,
        install_id: str,
        player_name: str,
        syster_payload: dict[str, object],
    ) -> int:
        training = (
            syster_payload.get("training")
            if isinstance(syster_payload.get("training"), dict)
            else {}
        )
        samples = (
            training.get("feedback_samples")
            if isinstance(training.get("feedback_samples"), list)
            else []
        )
        if not samples:
            return 0

        now_utc = datetime.now(timezone.utc)
        ingested = 0
        for item in samples[:20]:
            if not isinstance(item, dict):
                continue
            local_id = _as_int(item.get("local_id"))
            if local_id <= 0:
                continue

            ts_value = _as_float(item.get("ts"), 0.0)
            try:
                sample_ts = (
                    datetime.fromtimestamp(ts_value, tz=timezone.utc)
                    if ts_value > 0.0
                    else now_utc
                )
            except Exception:
                sample_ts = now_utc

            binds = {
                "install_id": install_id,
                "sample_local_id": local_id,
                "player_name": player_name,
                "sample_ts": sample_ts,
                "score_value": round(_as_float(item.get("score"), 0.0), 4),
                "notes_text": self._compact_text(item.get("notes", ""), 500),
                "prompt_text": self._compact_text(item.get("prompt", ""), 1000),
                "reply_text": self._compact_text(item.get("reply", ""), 1000),
            }
            cursor.execute(MERGE_SYSTER_FEEDBACK_SQL, binds)
            ingested += 1
        return ingested

    def syster_global_summary(self) -> dict[str, object]:
        summary = {"samples": 0, "avg_score": 0.0}
        with self.pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS sample_count, COALESCE(AVG(SCORE_VALUE), 0)
                    FROM GETHES_SYSTER_FEEDBACK
                    """
                )
                row = cur.fetchone()
                if row:
                    summary["samples"] = _as_int(row[0])
                    summary["avg_score"] = round(_as_float(row[1], 0.0), 4)
        return summary

    def heartbeat(self, payload: dict[str, object]) -> dict[str, object]:
        install_id = str(payload.get("install_id", "")).strip().lower().replace("-", "")[:64]
        if not install_id:
            raise ValueError("missing_install_id")

        player_name = sanitize_name(str(payload.get("player_name", "Guest")))
        version_tag = str(payload.get("version", "")).strip()[:32]
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        scores = payload.get("scores") if isinstance(payload.get("scores"), dict) else {}
        prefs = payload.get("preferences") if isinstance(payload.get("preferences"), dict) else {}
        syster_payload = payload.get("syster") if isinstance(payload.get("syster"), dict) else {}

        binds = {
            "install_id": install_id,
            "player_name": player_name,
            "version_tag": version_tag,
            "slot_id": _as_int(profile.get("slot_id")),
            "route_name": str(profile.get("route_name", ""))[:128],
            "story_page": _as_int(profile.get("story_page")),
            "story_total": _as_int(profile.get("story_total")),
            "achievements_unlocked": _as_int(profile.get("achievements_unlocked")),
            "achievements_total": _as_int(profile.get("achievements_total")),
            "snake_best_score": _as_int(scores.get("snake_best_score")),
            "snake_best_level": _as_int(scores.get("snake_best_level")),
            "snake_longest_length": _as_int(scores.get("snake_longest_length")),
            "rogue_best_depth": _as_int(scores.get("rogue_best_depth")),
            "rogue_best_gold": _as_int(scores.get("rogue_best_gold")),
            "rogue_best_kills": _as_int(scores.get("rogue_best_kills")),
            "rogue_runs": _as_int(scores.get("rogue_runs")),
            "rogue_wins": _as_int(scores.get("rogue_wins")),
            "graphics_mode": str(prefs.get("graphics", ""))[:16],
            "language_active": str(prefs.get("language_active", ""))[:8],
            "ui_scale": round(_as_float(prefs.get("ui_scale"), 1.0), 2),
            "theme_name": str(prefs.get("theme", ""))[:64],
        }

        syster_profile_synced = False
        syster_feedback_ingested = 0
        with self.pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(MERGE_SQL, binds)
                if syster_payload:
                    syster_profile_synced = self._upsert_syster_profile(
                        cur,
                        install_id=install_id,
                        player_name=player_name,
                        syster_payload=syster_payload,
                    )
                    syster_feedback_ingested = self._upsert_syster_feedback_samples(
                        cur,
                        install_id=install_id,
                        player_name=player_name,
                        syster_payload=syster_payload,
                    )
            conn.commit()

        online, users = self.presence()
        syster_global = self.syster_global_summary()
        return {
            "ok": True,
            "message": "synced",
            "players_online": online,
            "registered_users": users,
            "syster_profile_synced": bool(syster_profile_synced),
            "syster_feedback_ingested": int(syster_feedback_ingested),
            "syster_global_samples": int(syster_global.get("samples", 0) or 0),
            "syster_global_avg_score": float(syster_global.get("avg_score", 0.0) or 0.0),
            "server_time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def presence(self) -> tuple[int, int]:
        online = 0
        total = 0
        with self.pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM GETHES_TELEMETRY_PLAYERS
                    WHERE LAST_SEEN >= SYSTIMESTAMP - NUMTODSINTERVAL(:secs, 'SECOND')
                    """,
                    {"secs": int(self.online_window_seconds)},
                )
                row = cur.fetchone()
                if row:
                    online = _as_int(row[0])

                cur.execute("SELECT COUNT(*) FROM GETHES_TELEMETRY_PLAYERS")
                row = cur.fetchone()
                if row:
                    total = _as_int(row[0])
        return online, total


class TelemetryHandler(BaseHTTPRequestHandler):
    store: OracleTelemetryStore | None = None
    api_key: str = ""

    def do_GET(self) -> None:  # pragma: no cover - exercised manually
        if self.path.startswith("/health"):
            self._send_json(HTTPStatus.OK, {"ok": True, "service": "oracle_cloud"})
            return
        if self.path.startswith("/v1/telemetry/presence"):
            if not self._authorize():
                return
            if self.store is None:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "message": "store_unavailable"})
                return
            try:
                online, users = self.store.presence()
                syster = self.store.syster_global_summary()
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "message": str(exc)})
                return
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

    def do_POST(self) -> None:  # pragma: no cover - exercised manually
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
        length = int(raw_length)
        raw = self.rfile.read(length)
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
    parser = argparse.ArgumentParser(description="Gethes Oracle telemetry backend")
    parser.add_argument("--wallet-zip", type=Path, required=True, help="Path to Wallet_*.zip")
    parser.add_argument("--wallet-dir", type=Path, default=Path(".wallet_oracle"), help="Extracted wallet directory")
    parser.add_argument("--dsn", default="", help="Oracle TNS alias (e.g., gethes_high)")
    parser.add_argument("--db-user", default="", help="Oracle DB username")
    parser.add_argument("--db-password", default="", help="Oracle DB password")
    parser.add_argument("--wallet-password", default="", help="Wallet password (if required)")
    parser.add_argument("--api-key", default="", help="Optional API key for heartbeat/presence")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument("--port", type=int, default=8787, help="HTTP bind port")
    parser.add_argument("--online-window-seconds", type=int, default=120, help="Presence window")
    parser.add_argument("--tcp-connect-timeout", type=float, default=6.0, help="Oracle TCP connect timeout in seconds")
    parser.add_argument("--retry-count", type=int, default=1, help="Oracle connect retry count")
    parser.add_argument("--retry-delay", type=int, default=1, help="Oracle connect retry delay in seconds")
    parser.add_argument("--list-dsn", action="store_true", help="List TNS aliases and exit")
    return parser


def main() -> None:  # pragma: no cover - manual service entrypoint
    parser = build_arg_parser()
    args = parser.parse_args()

    wallet_dir, aliases = extract_wallet(args.wallet_zip, args.wallet_dir)
    if aliases:
        print(f"[oracle] Available TNS aliases: {', '.join(aliases)}")
    else:
        print("[oracle] No aliases found in tnsnames.ora")

    if args.list_dsn:
        return

    dsn = args.dsn.strip() or (aliases[0] if aliases else "")
    if not dsn:
        raise SystemExit("No Oracle DSN alias provided. Use --dsn <alias>.")
    if not args.db_user.strip() or not args.db_password.strip():
        raise SystemExit("Missing DB credentials. Use --db-user and --db-password.")

    print(
        "[oracle] Connecting to DB "
        f"(dsn={dsn}, tcp_timeout={args.tcp_connect_timeout}s, retries={args.retry_count}, retry_delay={args.retry_delay}s)..."
    )
    store = OracleTelemetryStore(
        wallet_dir=wallet_dir,
        dsn=dsn,
        db_user=args.db_user.strip(),
        db_password=args.db_password.strip(),
        wallet_password=args.wallet_password.strip(),
        online_window_seconds=args.online_window_seconds,
        tcp_connect_timeout=args.tcp_connect_timeout,
        retry_count=args.retry_count,
        retry_delay=args.retry_delay,
    )

    TelemetryHandler.store = store
    TelemetryHandler.api_key = args.api_key.strip()
    server = ThreadingHTTPServer((args.host, int(args.port)), TelemetryHandler)
    print(f"[oracle] Backend ready on http://{args.host}:{args.port}")
    print(f"[oracle] Using DSN alias: {dsn}")
    if TelemetryHandler.api_key:
        print("[oracle] API key auth: enabled")
    else:
        print("[oracle] API key auth: disabled")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[oracle] Shutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
