from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib import error as urlerror, parse as urlparse, request as urlrequest


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


def sanitize_email(value: str) -> str:
    token = value.strip().lower()
    if "@" not in token or "." not in token:
        return ""
    if len(token) > 190:
        return ""
    local, _, domain = token.partition("@")
    if not local or not domain or "." not in domain:
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789._+-@")
    if any(ch not in allowed for ch in token):
        return ""
    return token


def sanitize_password(value: str) -> str:
    token = value.strip()
    if len(token) < 8 or len(token) > 128:
        return ""
    return token


def normalize_login(value: str) -> str:
    return " ".join(value.strip().split()).lower()


def hash_password(password: str, salt: str) -> str:
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8", errors="ignore"),
        salt.encode("utf-8", errors="ignore"),
        180000,
    )
    return raw.hex()


class AwsSqliteTelemetryStore:
    def __init__(
        self,
        db_path: Path,
        online_window_seconds: int = 120,
        github_repo: str = "OrionTheProgrammer/Gethes",
        news_refresh_seconds: int = 600,
    ) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.online_window_seconds = max(30, int(online_window_seconds))
        self.github_repo = github_repo.strip() or "OrionTheProgrammer/Gethes"
        self.news_refresh_seconds = max(120, int(news_refresh_seconds))
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._news_last_refresh = 0.0
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

                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_login REAL NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    session_token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    install_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

                CREATE TABLE IF NOT EXISTS news_items (
                    item_key TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    published_at REAL NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at DESC);

                CREATE TABLE IF NOT EXISTS news_reads (
                    user_id INTEGER NOT NULL,
                    item_key TEXT NOT NULL,
                    read_at REAL NOT NULL,
                    PRIMARY KEY (user_id, item_key),
                    FOREIGN KEY(user_id) REFERENCES users(user_id),
                    FOREIGN KEY(item_key) REFERENCES news_items(item_key)
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

    def _read_json_url(self, url: str, timeout: float = 4.0) -> dict[str, object] | list[object]:
        req = urlrequest.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Gethes-Backend/1.0",
            },
            method="GET",
        )
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            return parsed
        return {}

    def _insert_news_item(
        self,
        *,
        item_key: str,
        source_type: str,
        title: str,
        summary: str,
        source_url: str,
        published_at: float,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO news_items (item_key, source_type, title, summary, source_url, published_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_key) DO UPDATE SET
                    title=excluded.title,
                    summary=excluded.summary,
                    source_url=excluded.source_url,
                    published_at=excluded.published_at
                """,
                (
                    self._compact(item_key, 190),
                    self._compact(source_type, 24),
                    self._compact(title, 180),
                    self._compact(summary, 700),
                    self._compact(source_url, 350),
                    float(published_at),
                    time.time(),
                ),
            )
            self._conn.commit()

    def refresh_news_from_github(self, repo: str = "") -> dict[str, int]:
        target_repo = (repo or self.github_repo).strip() or self.github_repo
        now = time.time()
        if (now - self._news_last_refresh) < float(self.news_refresh_seconds):
            return {"inserted": 0, "repo": 0}
        self._news_last_refresh = now

        inserted = 0
        # Latest release
        try:
            release_url = f"https://api.github.com/repos/{target_repo}/releases/latest"
            release_data = self._read_json_url(release_url)
            if isinstance(release_data, dict) and release_data.get("tag_name"):
                tag_name = self._compact(release_data.get("tag_name", ""), 80)
                title = self._compact(release_data.get("name", "") or f"Release {tag_name}", 180)
                body = self._compact(release_data.get("body", "") or "", 650)
                html_url = self._compact(release_data.get("html_url", ""), 350)
                published_raw = str(release_data.get("published_at", "")).strip()
                try:
                    published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00")).timestamp()
                except Exception:
                    published_at = now
                self._insert_news_item(
                    item_key=f"release:{tag_name}",
                    source_type="release",
                    title=title,
                    summary=body or f"New release published: {tag_name}",
                    source_url=html_url,
                    published_at=published_at,
                )
                inserted += 1
        except (urlerror.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            pass

        # Latest commits (light feed)
        try:
            commits_url = f"https://api.github.com/repos/{target_repo}/commits?per_page=5"
            commits_data = self._read_json_url(commits_url)
            if isinstance(commits_data, list):
                for item in commits_data:
                    if not isinstance(item, dict):
                        continue
                    sha = self._compact(str(item.get("sha", "")), 80)
                    if not sha:
                        continue
                    commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
                    message = self._compact(
                        (commit.get("message", "") if isinstance(commit, dict) else ""),
                        650,
                    )
                    title = self._compact(message.splitlines()[0] if message else f"Commit {sha[:7]}", 180)
                    html_url = self._compact(item.get("html_url", ""), 350)
                    date_raw = ""
                    if isinstance(commit, dict):
                        author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
                        date_raw = str(author.get("date", "")).strip() if isinstance(author, dict) else ""
                    try:
                        published_at = datetime.fromisoformat(date_raw.replace("Z", "+00:00")).timestamp()
                    except Exception:
                        published_at = now
                    self._insert_news_item(
                        item_key=f"commit:{sha}",
                        source_type="commit",
                        title=title,
                        summary=message or title,
                        source_url=html_url,
                        published_at=published_at,
                    )
                    inserted += 1
        except (urlerror.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            pass

        return {"inserted": inserted, "repo": 1}

    def _create_session(self, user_id: int, install_id: str, days_valid: int = 30) -> str:
        token = secrets.token_urlsafe(48)
        now_ts = time.time()
        expires = now_ts + max(1, int(days_valid)) * 86400
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (session_token, user_id, install_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    token,
                    int(user_id),
                    self._compact(install_id, 64),
                    now_ts,
                    expires,
                ),
            )
            self._conn.commit()
        return token

    def resolve_session_user(self, session_token: str) -> dict[str, object] | None:
        token = session_token.strip()
        if not token:
            return None
        now_ts = time.time()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT s.session_token, s.user_id, s.expires_at, u.username, u.email
                FROM sessions s
                JOIN users u ON u.user_id = s.user_id
                WHERE s.session_token = ?
                LIMIT 1
                """,
                (token,),
            ).fetchone()
        if row is None:
            return None
        expires_at = _as_float(row["expires_at"], 0.0)
        if expires_at < now_ts:
            with self._lock:
                self._conn.execute("DELETE FROM sessions WHERE session_token = ?", (token,))
                self._conn.commit()
            return None
        return {
            "user_id": _as_int(row["user_id"]),
            "username": self._compact(row["username"], 64),
            "email": self._compact(row["email"], 190),
            "session_token": token,
            "expires_at": expires_at,
        }

    def logout_session(self, session_token: str) -> bool:
        token = session_token.strip()
        if not token:
            return False
        with self._lock:
            cur = self._conn.execute("DELETE FROM sessions WHERE session_token = ?", (token,))
            self._conn.commit()
            return bool(cur.rowcount)

    def register_user(
        self,
        *,
        username: str,
        email: str,
        password: str,
        install_id: str,
    ) -> dict[str, object]:
        clean_user = sanitize_name(username)
        clean_email = sanitize_email(email)
        clean_pass = sanitize_password(password)
        clean_install = self._compact(install_id.strip().lower().replace("-", ""), 64)
        if not clean_install:
            raise ValueError("missing_install_id")
        if clean_user.lower() == "guest":
            raise ValueError("username_reserved")
        if not clean_email:
            raise ValueError("invalid_email")
        if not clean_pass:
            raise ValueError("invalid_password")

        user_lookup = clean_user.lower()
        salt = secrets.token_hex(16)
        pwd_hash = hash_password(clean_pass, salt)
        now_ts = time.time()
        with self._lock:
            existing = self._conn.execute(
                "SELECT user_id FROM users WHERE username = ? OR email = ? LIMIT 1",
                (user_lookup, clean_email),
            ).fetchone()
            if existing is not None:
                raise ValueError("user_exists")

            self._conn.execute(
                """
                INSERT INTO users (username, email, password_hash, password_salt, created_at, last_login, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (user_lookup, clean_email, pwd_hash, salt, now_ts, now_ts),
            )
            user_id = int(self._conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            self._conn.commit()

        session_token = self._create_session(user_id, clean_install)
        return {
            "ok": True,
            "user_id": user_id,
            "username": user_lookup,
            "email": clean_email,
            "session_token": session_token,
        }

    def login_user(self, *, login: str, password: str, install_id: str) -> dict[str, object]:
        token = normalize_login(login)
        clean_pass = sanitize_password(password)
        clean_install = self._compact(install_id.strip().lower().replace("-", ""), 64)
        if not token:
            raise ValueError("missing_login")
        if not clean_pass:
            raise ValueError("invalid_password")
        if not clean_install:
            raise ValueError("missing_install_id")

        with self._lock:
            row = self._conn.execute(
                """
                SELECT user_id, username, email, password_hash, password_salt, is_active
                FROM users
                WHERE username = ? OR email = ?
                LIMIT 1
                """,
                (token, token),
            ).fetchone()
            if row is None:
                raise ValueError("invalid_credentials")
            if _as_int(row["is_active"], 0) == 0:
                raise ValueError("user_disabled")

            expected = str(row["password_hash"] or "")
            salt = str(row["password_salt"] or "")
            if not expected or not salt:
                raise ValueError("invalid_credentials")
            incoming = hash_password(clean_pass, salt)
            if incoming != expected:
                raise ValueError("invalid_credentials")

            user_id = _as_int(row["user_id"], 0)
            if user_id <= 0:
                raise ValueError("invalid_credentials")

            now_ts = time.time()
            self._conn.execute(
                "UPDATE users SET last_login = ? WHERE user_id = ?",
                (now_ts, user_id),
            )
            self._conn.commit()

        session_token = self._create_session(user_id, clean_install)
        return {
            "ok": True,
            "user_id": user_id,
            "username": self._compact(row["username"], 64),
            "email": self._compact(row["email"], 190),
            "session_token": session_token,
        }

    def fetch_news_for_user(
        self,
        *,
        session_token: str,
        repo: str = "",
        limit: int = 12,
        mark_seen: bool = True,
    ) -> dict[str, object]:
        user = self.resolve_session_user(session_token)
        if user is None:
            raise ValueError("invalid_session")

        self.refresh_news_from_github(repo=repo)
        user_id = _as_int(user.get("user_id"), 0)
        fetch_limit = max(1, min(30, int(limit)))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT n.item_key, n.source_type, n.title, n.summary, n.source_url, n.published_at,
                       CASE WHEN r.item_key IS NULL THEN 0 ELSE 1 END AS seen
                FROM news_items n
                LEFT JOIN news_reads r
                    ON r.user_id = ? AND r.item_key = n.item_key
                ORDER BY n.published_at DESC, n.created_at DESC
                LIMIT ?
                """,
                (user_id, fetch_limit),
            ).fetchall()

            items: list[dict[str, object]] = []
            unread = 0
            now_ts = time.time()
            for row in rows:
                seen = bool(_as_int(row["seen"], 0))
                if not seen:
                    unread += 1
                    if mark_seen:
                        self._conn.execute(
                            """
                            INSERT INTO news_reads (user_id, item_key, read_at)
                            VALUES (?, ?, ?)
                            ON CONFLICT(user_id, item_key) DO UPDATE SET read_at=excluded.read_at
                            """,
                            (user_id, str(row["item_key"]), now_ts),
                        )
                items.append(
                    {
                        "key": str(row["item_key"]),
                        "type": str(row["source_type"]),
                        "title": str(row["title"]),
                        "summary": str(row["summary"]),
                        "url": str(row["source_url"]),
                        "published_at": float(row["published_at"]),
                        "seen": seen,
                    }
                )
            self._conn.commit()
        return {
            "ok": True,
            "unread": unread,
            "items": items,
            "repo": (repo or self.github_repo).strip() or self.github_repo,
        }

    def _upsert_player(self, payload: dict[str, object]) -> str:
        install_id = str(payload.get("install_id", "")).strip().lower().replace("-", "")[:64]
        if not install_id:
            raise ValueError("missing_install_id")

        auth_user = payload.get("auth_user") if isinstance(payload.get("auth_user"), dict) else {}
        auth_name = ""
        if isinstance(auth_user, dict):
            auth_name = sanitize_name(str(auth_user.get("username", "")))
        player_name = auth_name or sanitize_name(str(payload.get("player_name", "Guest")))
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
        path_info = urlparse.urlsplit(self.path)
        route = path_info.path
        query = urlparse.parse_qs(path_info.query, keep_blank_values=False)

        if route == "/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "service": "aws_sqlite_cloud"})
            return
        if route.startswith("/v1/"):
            if not self._authorize():
                return
        if route == "/v1/telemetry/presence":
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
        if route == "/v1/auth/me":
            if self.store is None:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "message": "store_unavailable"})
                return
            session = self._session_token()
            user = self.store.resolve_session_user(session)
            if user is None:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "message": "invalid_session"})
                return
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "user_id": int(user.get("user_id", 0) or 0),
                    "username": str(user.get("username", "")),
                    "email": str(user.get("email", "")),
                    "expires_at": float(user.get("expires_at", 0.0) or 0.0),
                },
            )
            return
        if route == "/v1/news":
            if self.store is None:
                self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "message": "store_unavailable"})
                return
            session = self._session_token()
            limit_raw = ""
            if isinstance(query.get("limit"), list) and query["limit"]:
                limit_raw = str(query["limit"][0])
            mark_raw = ""
            if isinstance(query.get("mark_seen"), list) and query["mark_seen"]:
                mark_raw = str(query["mark_seen"][0])
            repo = ""
            if isinstance(query.get("repo"), list) and query["repo"]:
                repo = str(query["repo"][0]).strip()
            limit = max(1, min(30, _as_int(limit_raw, 12)))
            mark_seen = mark_raw.strip().lower() not in {"0", "false", "off", "no"}
            try:
                data = self.store.fetch_news_for_user(
                    session_token=session,
                    repo=repo,
                    limit=limit,
                    mark_seen=mark_seen,
                )
            except ValueError as exc:
                status = HTTPStatus.UNAUTHORIZED if str(exc) == "invalid_session" else HTTPStatus.BAD_REQUEST
                self._send_json(status, {"ok": False, "message": str(exc)})
                return
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "message": str(exc)})
                return
            self._send_json(HTTPStatus.OK, data)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "not_found"})

    def do_POST(self) -> None:  # pragma: no cover
        path_info = urlparse.urlsplit(self.path)
        route = path_info.path
        if not route.startswith("/v1/"):
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "not_found"})
            return
        if route not in {
            "/v1/telemetry/heartbeat",
            "/v1/auth/register",
            "/v1/auth/login",
            "/v1/auth/logout",
        }:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "not_found"})
            return
        if not self._authorize():
            return
        if self.store is None:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "message": "store_unavailable"})
            return

        payload = self._read_json_payload()
        if payload is None:
            return

        if route == "/v1/telemetry/heartbeat":
            session = self._session_token()
            user = self.store.resolve_session_user(session) if session else None
            if user is not None:
                payload["auth_user"] = {
                    "user_id": int(user.get("user_id", 0) or 0),
                    "username": str(user.get("username", "")),
                    "email": str(user.get("email", "")),
                }
            try:
                data = self.store.heartbeat(payload)
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": str(exc)})
                return
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "message": str(exc)})
                return
            self._send_json(HTTPStatus.OK, data)
            return

        if route == "/v1/auth/register":
            username = str(payload.get("username", "")).strip()
            email = str(payload.get("email", "")).strip()
            password = str(payload.get("password", ""))
            install_id = str(payload.get("install_id", "")).strip()
            try:
                data = self.store.register_user(
                    username=username,
                    email=email,
                    password=password,
                    install_id=install_id,
                )
            except ValueError as exc:
                self._send_json(self._error_status_for_auth(str(exc)), {"ok": False, "message": str(exc)})
                return
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "message": str(exc)})
                return
            self._send_json(HTTPStatus.OK, data)
            return

        if route == "/v1/auth/login":
            login = str(payload.get("login", "")).strip()
            password = str(payload.get("password", ""))
            install_id = str(payload.get("install_id", "")).strip()
            try:
                data = self.store.login_user(login=login, password=password, install_id=install_id)
            except ValueError as exc:
                self._send_json(self._error_status_for_auth(str(exc)), {"ok": False, "message": str(exc)})
                return
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "message": str(exc)})
                return
            self._send_json(HTTPStatus.OK, data)
            return

        if route == "/v1/auth/logout":
            session = self._session_token() or str(payload.get("session_token", "")).strip()
            if not session:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "missing_session"})
                return
            ok = self.store.logout_session(session)
            self._send_json(HTTPStatus.OK, {"ok": bool(ok), "message": ("logged_out" if ok else "session_not_found")})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "not_found"})

    @staticmethod
    def _error_status_for_auth(code: str) -> HTTPStatus:
        if code in {"invalid_credentials", "invalid_session"}:
            return HTTPStatus.UNAUTHORIZED
        if code in {"user_exists"}:
            return HTTPStatus.CONFLICT
        if code in {"user_disabled"}:
            return HTTPStatus.FORBIDDEN
        return HTTPStatus.BAD_REQUEST

    def _read_json_payload(self) -> dict[str, object] | None:
        raw_length = self.headers.get("Content-Length", "").strip()
        if not raw_length.isdigit():
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "missing_content_length"})
            return None
        raw = self.rfile.read(int(raw_length))
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "invalid_json"})
            return None
        if not isinstance(payload, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "message": "invalid_payload"})
            return None
        return payload

    def _session_token(self) -> str:
        token = self.headers.get("X-Gethes-Session", "").strip()
        if token:
            return token
        return self.headers.get("X-Session-Token", "").strip()

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
    parser.add_argument(
        "--github-repo",
        default="OrionTheProgrammer/Gethes",
        help="Repo for news feed polling, e.g. OrionTheProgrammer/Gethes",
    )
    parser.add_argument(
        "--news-refresh-seconds",
        type=int,
        default=600,
        help="Minimum interval between GitHub news refreshes",
    )
    return parser


def main() -> None:  # pragma: no cover
    parser = build_arg_parser()
    args = parser.parse_args()

    store = AwsSqliteTelemetryStore(
        db_path=args.db_path,
        online_window_seconds=args.online_window_seconds,
        github_repo=args.github_repo,
        news_refresh_seconds=args.news_refresh_seconds,
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
