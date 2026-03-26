from __future__ import annotations

from dataclasses import dataclass
import json
from urllib import error, parse, request

from . import __version__

try:
    import httpx
except ImportError:  # pragma: no cover - optional dependency fallback
    httpx = None


@dataclass(frozen=True)
class CloudResponse:
    ok: bool
    status_code: int
    message: str
    payload: dict[str, object]


class CloudSyncClient:
    def __init__(
        self,
        endpoint: str = "",
        api_key: str = "",
        session_token: str = "",
        timeout: float = 2.6,
    ) -> None:
        self.endpoint = self.normalize_endpoint(endpoint)
        self.api_key = api_key.strip()
        self.session_token = session_token.strip()
        self.timeout = max(0.8, min(9.0, float(timeout)))

    @staticmethod
    def normalize_endpoint(value: str) -> str:
        endpoint = value.strip()
        if not endpoint:
            return ""
        endpoint = endpoint.rstrip("/")
        if endpoint.endswith("/v1/telemetry"):
            endpoint = endpoint[: -len("/v1/telemetry")]
        return endpoint

    def configure(self, endpoint: str, api_key: str = "", session_token: str | None = None) -> None:
        self.endpoint = self.normalize_endpoint(endpoint)
        self.api_key = api_key.strip()
        if session_token is not None:
            self.session_token = session_token.strip()

    def is_linked(self) -> bool:
        return bool(self.endpoint)

    def has_session(self) -> bool:
        return bool(self.session_token)

    def set_session(self, token: str) -> None:
        self.session_token = token.strip()

    def clear_session(self) -> None:
        self.session_token = ""

    def masked_key(self) -> str:
        token = self.api_key.strip()
        if not token:
            return "-"
        if len(token) <= 8:
            return "*" * len(token)
        return f"{token[:4]}...{token[-4:]}"

    def push_snapshot(self, payload: dict[str, object]) -> CloudResponse:
        if not self.is_linked():
            return CloudResponse(False, 0, "not_linked", {})
        return self._request_json(
            method="POST",
            path="/v1/telemetry/heartbeat",
            payload=payload,
        )

    def fetch_presence(self) -> CloudResponse:
        if not self.is_linked():
            return CloudResponse(False, 0, "not_linked", {})
        return self._request_json(
            method="GET",
            path="/v1/telemetry/presence",
        )

    def register(
        self,
        *,
        username: str,
        email: str,
        password: str,
        install_id: str,
    ) -> CloudResponse:
        if not self.is_linked():
            return CloudResponse(False, 0, "not_linked", {})
        return self._request_json(
            method="POST",
            path="/v1/auth/register",
            payload={
                "username": username,
                "email": email,
                "password": password,
                "install_id": install_id,
            },
        )

    def login(self, *, login: str, password: str, install_id: str) -> CloudResponse:
        if not self.is_linked():
            return CloudResponse(False, 0, "not_linked", {})
        return self._request_json(
            method="POST",
            path="/v1/auth/login",
            payload={
                "login": login,
                "password": password,
                "install_id": install_id,
            },
        )

    def logout(self) -> CloudResponse:
        if not self.is_linked():
            return CloudResponse(False, 0, "not_linked", {})
        if not self.has_session():
            return CloudResponse(False, 0, "not_authenticated", {})
        response = self._request_json(
            method="POST",
            path="/v1/auth/logout",
            payload={},
        )
        if response.ok:
            self.clear_session()
        return response

    def fetch_me(self) -> CloudResponse:
        if not self.is_linked():
            return CloudResponse(False, 0, "not_linked", {})
        if not self.has_session():
            return CloudResponse(False, 0, "not_authenticated", {})
        return self._request_json(
            method="GET",
            path="/v1/auth/me",
        )

    def fetch_news(
        self,
        *,
        limit: int = 8,
        mark_seen: bool = False,
        repo: str = "",
    ) -> CloudResponse:
        if not self.is_linked():
            return CloudResponse(False, 0, "not_linked", {})
        if not self.has_session():
            return CloudResponse(False, 0, "not_authenticated", {})
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            limit_value = 8
        payload: dict[str, object] = {
            "limit": max(1, min(30, limit_value)),
            "mark_seen": 1 if mark_seen else 0,
        }
        if repo.strip():
            payload["repo"] = repo.strip()
        return self._request_json(
            method="GET",
            path="/v1/news",
            payload=payload,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> CloudResponse:
        if httpx is not None:
            response = self._request_httpx(method=method, path=path, payload=payload)
            if response is not None:
                return response
        return self._request_urllib(method=method, path=path, payload=payload)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain",
            "User-Agent": f"Gethes-Cloud/{__version__}",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-API-Key"] = self.api_key
        if self.session_token:
            headers["X-Gethes-Session"] = self.session_token
        return headers

    def _build_url(self, path: str, payload: dict[str, object] | None) -> str:
        base = self.endpoint.rstrip("/")
        url = f"{base}{path}"
        if payload:
            qs = parse.urlencode(payload, doseq=False)
            if qs:
                return f"{url}?{qs}"
        return url

    def _request_httpx(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None,
    ) -> CloudResponse | None:
        if httpx is None:
            return None
        url = self._build_url(path=path, payload=(payload if method == "GET" else None))
        headers = self._headers()
        try:
            timeout = httpx.Timeout(self.timeout)
            with httpx.Client(timeout=timeout) as client:
                if method == "POST":
                    resp = client.post(url, json=(payload or {}), headers=headers)
                else:
                    resp = client.get(url, headers=headers)
        except (httpx.RequestError, httpx.TimeoutException, ValueError):
            return None

        data = self._parse_json_body(resp.text)
        message = self._extract_message(resp.status_code, data)
        return CloudResponse(resp.status_code < 400, int(resp.status_code), message, data)

    def _request_urllib(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None,
    ) -> CloudResponse:
        headers = self._headers()
        body: bytes | None = None
        if method == "POST":
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
            url = self._build_url(path=path, payload=None)
        else:
            url = self._build_url(path=path, payload=payload)

        req = request.Request(url, data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout) as raw:
                status_code = int(raw.getcode() or 0)
                response_body = raw.read()
        except error.HTTPError as exc:
            status_code = int(getattr(exc, "code", 0) or 0)
            response_body = exc.read() if hasattr(exc, "read") else b""
        except (error.URLError, TimeoutError, ValueError):
            return CloudResponse(False, 0, "network_error", {})

        text = response_body.decode("utf-8", errors="replace").strip() if response_body else ""
        data = self._parse_json_body(text)
        message = self._extract_message(status_code, data)
        return CloudResponse(status_code < 400, status_code, message, data)

    @staticmethod
    def _parse_json_body(text: str) -> dict[str, object]:
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}

    @staticmethod
    def _extract_message(status_code: int, payload: dict[str, object]) -> str:
        for key in ("message", "status", "detail", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        if status_code == 0:
            return "network_error"
        if status_code < 400:
            return "ok"
        return f"http_{status_code}"
