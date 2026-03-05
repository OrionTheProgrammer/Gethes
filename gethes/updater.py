from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Callable
from urllib import error, request


GITHUB_API = "https://api.github.com"
DEFAULT_TIMEOUT = 8.0


@dataclass(frozen=True)
class UpdateInfo:
    repo: str
    current_version: str
    latest_version: str
    tag_name: str
    release_name: str
    installer_name: str
    installer_url: str
    html_url: str


class UpdateManager:
    def __init__(self, current_version: str, repo: str = "") -> None:
        self.current_version = current_version.strip() or "0.0.0"
        self.repo = self._normalize_repo(repo)

    def set_repo(self, repo: str) -> bool:
        normalized = self._normalize_repo(repo)
        if not normalized:
            return False
        self.repo = normalized
        return True

    def clear_repo(self) -> None:
        self.repo = ""

    def has_repo(self) -> bool:
        return bool(self.repo)

    def check_latest(self) -> tuple[str, UpdateInfo | None]:
        if not self.repo:
            return "repo_missing", None

        url = f"{GITHUB_API}/repos/{self.repo}/releases/latest"
        payload = self._fetch_json(url)
        if payload is None:
            return "network_error", None

        if not isinstance(payload, dict):
            return "invalid_response", None

        tag_name = str(payload.get("tag_name", "")).strip()
        if not tag_name:
            return "invalid_response", None

        latest_version = self._clean_version(tag_name)
        if not latest_version:
            return "invalid_response", None

        release_name = str(payload.get("name", "")).strip() or tag_name
        html_url = str(payload.get("html_url", "")).strip()
        asset = self._pick_installer_asset(payload.get("assets"))
        if asset is None:
            return "installer_missing", None

        update = UpdateInfo(
            repo=self.repo,
            current_version=self.current_version,
            latest_version=latest_version,
            tag_name=tag_name,
            release_name=release_name,
            installer_name=asset["name"],
            installer_url=asset["url"],
            html_url=html_url,
        )

        if self._compare_versions(update.latest_version, self.current_version) > 0:
            return "available", update
        return "up_to_date", update

    def download_installer(
        self,
        update: UpdateInfo,
        output_dir: Path,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        file_name = self._safe_filename(update.installer_name)
        target = output_dir / file_name
        tmp_target = target.with_suffix(target.suffix + ".part")

        req = request.Request(
            update.installer_url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "Gethes-Updater/0.01",
            },
            method="GET",
        )

        try:
            with request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                total = 0
                total_hdr = resp.headers.get("Content-Length")
                if total_hdr and total_hdr.isdigit():
                    total = int(total_hdr)

                downloaded = 0
                with tmp_target.open("wb") as fh:
                    while True:
                        chunk = resp.read(1024 * 64)
                        if not chunk:
                            break
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback is not None:
                            progress_callback(downloaded, total)
        except (error.URLError, error.HTTPError, OSError, TimeoutError, ValueError) as exc:
            raise RuntimeError(f"download_failed: {exc}") from exc

        if target.exists():
            target.unlink()
        tmp_target.rename(target)
        return target

    def launch_installer(self, installer_path: Path) -> bool:
        if not installer_path.exists():
            return False
        try:
            subprocess.Popen([str(installer_path)])
            return True
        except OSError:
            return False

    @staticmethod
    def _normalize_repo(repo: str) -> str:
        raw = repo.strip().strip("/")
        if not raw:
            return ""
        if raw.startswith("https://github.com/"):
            raw = raw[len("https://github.com/") :]
        if raw.endswith(".git"):
            raw = raw[:-4]

        parts = [p for p in raw.split("/") if p]
        if len(parts) != 2:
            return ""

        owner, name = parts
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner):
            return ""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            return ""
        return f"{owner}/{name}"

    @staticmethod
    def _fetch_json(url: str) -> dict[str, object] | list[object] | None:
        req = request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Gethes-Updater/0.01",
            },
            method="GET",
        )

        try:
            with request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                raw = resp.read()
        except (error.URLError, error.HTTPError, TimeoutError, ValueError):
            return None

        if not raw:
            return None

        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None

        if isinstance(payload, (dict, list)):
            return payload
        return None

    @staticmethod
    def _pick_installer_asset(raw_assets: object) -> dict[str, str] | None:
        if not isinstance(raw_assets, list):
            return None

        scored: list[tuple[int, dict[str, str]]] = []
        for item in raw_assets:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            url = str(item.get("url", "")).strip()
            if not name or not url:
                continue
            lower = name.lower()
            if not lower.endswith(".exe"):
                continue

            score = 0
            if "setup" in lower or "installer" in lower:
                score += 4
            if "gethes" in lower:
                score += 2
            if "portable" in lower or "onefile" in lower:
                score -= 2

            scored.append((score, {"name": name, "url": url}))

        if not scored:
            return None
        scored.sort(key=lambda row: row[0], reverse=True)
        return scored[0][1]

    @staticmethod
    def _clean_version(tag_or_version: str) -> str:
        token = tag_or_version.strip().lower()
        if token.startswith("v"):
            token = token[1:]
        allowed = re.findall(r"[0-9]+", token)
        if not allowed:
            return ""
        return ".".join(allowed[:4])

    @staticmethod
    def _compare_versions(left: str, right: str) -> int:
        def parse(value: str) -> tuple[int, ...]:
            nums = [int(part) for part in value.split(".") if part.isdigit()]
            while len(nums) < 4:
                nums.append(0)
            return tuple(nums[:4])

        lv = parse(left)
        rv = parse(right)
        if lv > rv:
            return 1
        if lv < rv:
            return -1
        return 0

    @staticmethod
    def _safe_filename(name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
        if cleaned.lower().endswith(".exe"):
            return cleaned
        return f"{cleaned}.exe"
