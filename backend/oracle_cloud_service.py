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

    def _ensure_schema(self) -> None:
        try:
            with self.pool.acquire() as conn:
                with conn.cursor() as cur:
                    cur.execute(CREATE_TABLE_SQL)
                conn.commit()
        except Exception as exc:
            if self._oracle_code(exc) == 955:
                return
            raise

    def heartbeat(self, payload: dict[str, object]) -> dict[str, object]:
        install_id = str(payload.get("install_id", "")).strip().lower().replace("-", "")[:64]
        if not install_id:
            raise ValueError("missing_install_id")

        player_name = sanitize_name(str(payload.get("player_name", "Guest")))
        version_tag = str(payload.get("version", "")).strip()[:32]
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        scores = payload.get("scores") if isinstance(payload.get("scores"), dict) else {}
        prefs = payload.get("preferences") if isinstance(payload.get("preferences"), dict) else {}

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

        with self.pool.acquire() as conn:
            with conn.cursor() as cur:
                cur.execute(MERGE_SQL, binds)
            conn.commit()

        online, users = self.presence()
        return {
            "ok": True,
            "message": "synced",
            "players_online": online,
            "registered_users": users,
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
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "message": str(exc)})
                return
            self._send_json(HTTPStatus.OK, {"players_online": online, "registered_users": users})
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
