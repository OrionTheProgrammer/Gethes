from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Callable
from urllib import error, request

from . import __version__


GITHUB_API = "https://api.github.com"
DEFAULT_TIMEOUT = 8.0


@dataclass(frozen=True)
class UpdateInfo:
    repo: str
    current_version: str
    latest_version: str
    tag_name: str
    release_name: str
    html_url: str
    release_notes: str = ""
    installer_name: str = ""
    installer_url: str = ""
    portable_name: str = ""
    portable_url: str = ""
    checksum_name: str = ""
    checksum_url: str = ""


class UpdateManager:
    def __init__(
        self,
        current_version: str,
        repo: str = "",
        cache_dir: Path | None = None,
    ) -> None:
        self.current_version = current_version.strip() or "0.0.0"
        self.repo = self._normalize_repo(repo)
        self.cache_dir = cache_dir

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
        payload = self._fetch_release_payload(url)
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

        installer_asset = self._pick_installer_asset(payload.get("assets"))
        portable_asset = self._pick_portable_asset(payload.get("assets"))
        checksum_asset = self._pick_checksum_asset(payload.get("assets"))
        if installer_asset is None and portable_asset is None:
            return "asset_missing", None

        update = UpdateInfo(
            repo=self.repo,
            current_version=self.current_version,
            latest_version=latest_version,
            tag_name=tag_name,
            release_name=release_name,
            html_url=html_url,
            release_notes=str(payload.get("body", "")).strip(),
            installer_name=(installer_asset["name"] if installer_asset is not None else ""),
            installer_url=(installer_asset["url"] if installer_asset is not None else ""),
            portable_name=(portable_asset["name"] if portable_asset is not None else ""),
            portable_url=(portable_asset["url"] if portable_asset is not None else ""),
            checksum_name=(checksum_asset["name"] if checksum_asset is not None else ""),
            checksum_url=(checksum_asset["url"] if checksum_asset is not None else ""),
        )

        if self._compare_versions(update.latest_version, self.current_version) > 0:
            return "available", update
        return "up_to_date", update

    def cleanup_update_artifacts(
        self,
        output_dir: Path,
        keep_recent: int = 8,
        max_age_days: int = 21,
    ) -> None:
        if not output_dir.exists() or not output_dir.is_dir():
            return

        now_ts = time.time()
        candidates: list[tuple[float, Path]] = []
        keep_recent = max(1, int(keep_recent))
        max_age_seconds = max(1, int(max_age_days)) * 86400

        for path in output_dir.iterdir():
            name = path.name.lower()
            if name == "cache":
                continue

            if name.startswith("_update_tmp_") or name.startswith("_update_backup_"):
                self._safe_remove(path)
                continue
            if name.startswith("apply_update_") and name.endswith(".ps1"):
                self._safe_remove(path)
                continue
            if name.endswith(".part"):
                self._safe_remove(path)
                continue
            if not path.is_file():
                continue

            suffix = path.suffix.lower()
            if suffix not in {".exe", ".zip", ".txt", ".sha256", ".bin", ".ps1", ".log"}:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            candidates.append((mtime, path))

        candidates.sort(key=lambda row: row[0], reverse=True)
        for index, (mtime, path) in enumerate(candidates):
            if index < keep_recent:
                continue
            if (now_ts - mtime) < max_age_seconds:
                continue
            self._safe_remove(path)

    def download_installer(
        self,
        update: UpdateInfo,
        output_dir: Path,
        progress_callback: Callable[[int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        if not update.installer_url or not update.installer_name:
            raise RuntimeError("installer_missing")
        return self._download_asset(
            url=update.installer_url,
            output_dir=output_dir,
            file_name=update.installer_name,
            progress_callback=progress_callback,
            accept="application/octet-stream",
            cancel_event=cancel_event,
        )

    def download_portable_zip(
        self,
        update: UpdateInfo,
        output_dir: Path,
        progress_callback: Callable[[int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        if not update.portable_url or not update.portable_name:
            raise RuntimeError("portable_missing")
        return self._download_asset(
            url=update.portable_url,
            output_dir=output_dir,
            file_name=update.portable_name,
            progress_callback=progress_callback,
            accept="application/octet-stream",
            cancel_event=cancel_event,
        )

    def verify_asset_checksum(
        self,
        asset_path: Path,
        update: UpdateInfo,
        output_dir: Path,
        cancel_event: threading.Event | None = None,
        require_checksum: bool = True,
    ) -> tuple[bool, str]:
        if not asset_path.exists():
            return False, "asset_not_found"
        if not update.checksum_url or not update.checksum_name:
            if require_checksum:
                return False, "checksum_missing_required"
            return True, "checksum_missing"

        checksum_file = self._download_asset(
            url=update.checksum_url,
            output_dir=output_dir,
            file_name=update.checksum_name,
            accept="application/octet-stream",
            cancel_event=cancel_event,
        )

        try:
            content = checksum_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False, "checksum_read_failed"

        expected = self._parse_checksum_from_text(content, asset_path.name)
        if not expected:
            return False, "checksum_entry_missing"

        actual = self._sha256_file(asset_path)
        if not actual:
            return False, "checksum_hash_failed"
        if actual.lower() != expected.lower():
            return False, "checksum_mismatch"
        return True, "checksum_ok"

    def expected_download_path(self, update: UpdateInfo, output_dir: Path, method: str) -> Path | None:
        normalized = method.strip().lower()
        if normalized == "portable":
            file_name = update.portable_name
        elif normalized == "installer":
            file_name = update.installer_name
        else:
            return None

        if not file_name.strip():
            return None
        clean_name = self._safe_filename(file_name)
        if not clean_name:
            return None
        return output_dir / clean_name

    def find_cached_download(self, update: UpdateInfo, output_dir: Path, method: str) -> Path | None:
        candidate = self.expected_download_path(update, output_dir, method)
        if candidate is None:
            return None
        if not candidate.exists() or not candidate.is_file():
            return None
        return candidate

    def _download_asset(
        self,
        url: str,
        output_dir: Path,
        file_name: str,
        progress_callback: Callable[[int, int], None] | None = None,
        accept: str = "application/octet-stream",
        cancel_event: threading.Event | None = None,
        max_retries: int = 3,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_file_name = self._safe_filename(file_name)
        target = output_dir / safe_file_name
        tmp_target = target.with_suffix(target.suffix + ".part")

        req = request.Request(
            url,
            headers={
                "Accept": accept,
                "User-Agent": f"Gethes-Updater/{__version__}",
            },
            method="GET",
        )

        retries = max(1, int(max_retries))
        for attempt in range(1, retries + 1):
            try:
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("cancelled")
                with request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                    total = 0
                    total_hdr = resp.headers.get("Content-Length")
                    if total_hdr and total_hdr.isdigit():
                        total = int(total_hdr)

                    downloaded = 0
                    with tmp_target.open("wb") as fh:
                        while True:
                            if cancel_event is not None and cancel_event.is_set():
                                raise RuntimeError("cancelled")
                            chunk = resp.read(1024 * 64)
                            if not chunk:
                                break
                            fh.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback is not None:
                                progress_callback(downloaded, total)
                break
            except RuntimeError:
                tmp_target.unlink(missing_ok=True)
                raise
            except (error.URLError, error.HTTPError, OSError, TimeoutError, ValueError) as exc:
                tmp_target.unlink(missing_ok=True)
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("cancelled") from exc
                if attempt >= retries:
                    raise RuntimeError(f"download_failed: {exc}") from exc
                time.sleep(min(1.2 * attempt, 3.0))

        if target.exists():
            target.unlink()
        tmp_target.rename(target)
        return target

    def launch_installer(self, installer_path: Path, silent: bool = True) -> bool:
        if not installer_path.exists():
            return False

        args = [str(installer_path)]
        if silent:
            args.extend(
                [
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    "/NOCANCEL",
                    "/SP-",
                ]
            )

        try:
            subprocess.Popen(args)
            return True
        except OSError:
            return False

    def can_self_update_portable(self, app_dir: Path) -> bool:
        if not app_dir.exists() or not app_dir.is_dir():
            return False

        probe_name = f".gethes_update_probe_{os.getpid()}"
        probe = app_dir / probe_name
        try:
            probe.write_text("ok", encoding="ascii")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def can_portable_update(self, app_dir: Path) -> bool:
        if self.can_self_update_portable(app_dir):
            return True
        return self._supports_elevated_portable_update(app_dir)

    def launch_portable_self_update(
        self,
        zip_path: Path,
        app_dir: Path,
        exe_path: Path,
        working_dir: Path,
    ) -> str:
        if not zip_path.exists() or not exe_path.exists():
            return "unavailable"
        if not app_dir.exists() or not app_dir.is_dir():
            return "unavailable"

        try:
            working_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return "unavailable"

        needs_elevation = not self.can_self_update_portable(app_dir)
        if needs_elevation and not self._supports_elevated_portable_update(app_dir):
            return "unavailable"

        powershell_exe = self._resolve_powershell_executable()
        if not powershell_exe:
            return "unavailable"

        script_path = working_dir / f"apply_update_{os.getpid()}.ps1"
        script = self._portable_update_script()
        try:
            script_path.write_text(script, encoding="utf-8")
        except OSError:
            return "unavailable"

        launch_args = [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(script_path),
            "-ZipPath",
            str(zip_path),
            "-TargetDir",
            str(app_dir),
            "-ExePath",
            str(exe_path),
            "-WorkingDir",
            str(working_dir),
        ]
        launch_status = self._launch_powershell_process(
            powershell_exe,
            launch_args,
            elevated=needs_elevation,
        )
        if launch_status == "ok":
            if needs_elevation:
                return "launched_elevated"
            return "launched"
        if launch_status == "elevation_denied":
            return "elevation_denied"
        return "launch_failed"

    def _supports_elevated_portable_update(self, app_dir: Path) -> bool:
        if os.name != "nt":
            return False
        if not app_dir.exists() or not app_dir.is_dir():
            return False
        return bool(self._resolve_powershell_executable())

    @staticmethod
    def _portable_update_script() -> str:
        return "\n".join(
            [
                "param(",
                "  [Parameter(Mandatory=$true)][string]$ZipPath,",
                "  [Parameter(Mandatory=$true)][string]$TargetDir,",
                "  [Parameter(Mandatory=$true)][string]$ExePath,",
                "  [Parameter(Mandatory=$true)][string]$WorkingDir",
                ")",
                "$ErrorActionPreference = 'Stop'",
                "function Invoke-WithRetry {",
                "  param(",
                "    [Parameter(Mandatory=$true)][scriptblock]$Action,",
                "    [int]$MaxTries = 5,",
                "    [int]$DelayMs = 850",
                "  )",
                "  for ($i = 1; $i -le $MaxTries; $i++) {",
                "    try {",
                "      & $Action",
                "      return $true",
                "    } catch {",
                "      if ($i -ge $MaxTries) { return $false }",
                "      Start-Sleep -Milliseconds $DelayMs",
                "    }",
                "  }",
                "  return $false",
                "}",
                "Start-Sleep -Milliseconds 750",
                "$ready = $false",
                "$deadline = (Get-Date).AddSeconds(75)",
                "while ((Get-Date) -lt $deadline) {",
                "  try {",
                "    $probe = Join-Path $TargetDir '.gethes_probe'",
                "    Set-Content -Path $probe -Value 'ok' -Encoding ASCII",
                "    Remove-Item $probe -Force -ErrorAction SilentlyContinue",
                "    $ready = $true",
                "    break",
                "  } catch {",
                "    Start-Sleep -Milliseconds 850",
                "  }",
                "}",
                "if (-not $ready) { throw 'target_locked' }",
                "$tmpDir = Join-Path $WorkingDir ('_update_tmp_' + [System.Guid]::NewGuid().ToString('N'))",
                "if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue }",
                "Expand-Archive -Path $ZipPath -DestinationPath $tmpDir -Force",
                "$entries = @(Get-ChildItem -Path $tmpDir -Force)",
                "if ($entries.Count -eq 0) { throw 'archive_empty' }",
                "$backupRoot = Join-Path $WorkingDir ('_update_backup_' + [System.Guid]::NewGuid().ToString('N'))",
                "if (-not (Test-Path $backupRoot)) { New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null }",
                "$moved = New-Object System.Collections.Generic.List[string]",
                "$copied = New-Object System.Collections.Generic.List[string]",
                "try {",
                "  foreach ($entry in $entries) {",
                "    $targetPath = Join-Path $TargetDir $entry.Name",
                "    $backupPath = Join-Path $backupRoot $entry.Name",
                "    if (Test-Path $targetPath) {",
                "      $backupParent = Split-Path -Path $backupPath -Parent",
                "      if (-not (Test-Path $backupParent)) { New-Item -ItemType Directory -Path $backupParent -Force | Out-Null }",
                "      $movedOk = Invoke-WithRetry -Action { Move-Item -Path $targetPath -Destination $backupPath -Force }",
                "      if (-not $movedOk) { throw 'backup_move_failed' }",
                "      $moved.Add($entry.Name) | Out-Null",
                "    }",
                "    $copiedOk = Invoke-WithRetry -Action { Copy-Item -Path $entry.FullName -Destination $targetPath -Recurse -Force }",
                "    if (-not $copiedOk) { throw 'copy_failed' }",
                "    $copied.Add($entry.Name) | Out-Null",
                "  }",
                "} catch {",
                "  foreach ($name in $copied) {",
                "    $targetPath = Join-Path $TargetDir $name",
                "    if (Test-Path $targetPath) { Remove-Item -Path $targetPath -Recurse -Force -ErrorAction SilentlyContinue }",
                "  }",
                "  foreach ($name in $moved) {",
                "    $targetPath = Join-Path $TargetDir $name",
                "    $backupPath = Join-Path $backupRoot $name",
                "    if (Test-Path $backupPath) {",
                "      $targetParent = Split-Path -Path $targetPath -Parent",
                "      if (-not (Test-Path $targetParent)) { New-Item -ItemType Directory -Path $targetParent -Force | Out-Null }",
                "      Move-Item -Path $backupPath -Destination $targetPath -Force -ErrorAction SilentlyContinue",
                "    }",
                "  }",
                "  throw",
                "}",
                "if (Test-Path $backupRoot) { Remove-Item $backupRoot -Recurse -Force -ErrorAction SilentlyContinue }",
                "Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue",
                "Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue",
                "Start-Process -FilePath $ExePath | Out-Null",
                "Remove-Item $PSCommandPath -Force -ErrorAction SilentlyContinue",
            ]
        )

    def _launch_powershell_process(
        self,
        powershell_exe: str,
        args: list[str],
        elevated: bool,
    ) -> str:
        if elevated:
            return self._launch_powershell_elevated(powershell_exe, args)
        try:
            subprocess.Popen([powershell_exe, *args])
            return "ok"
        except OSError:
            return "launch_failed"

    @staticmethod
    def _launch_powershell_elevated(powershell_exe: str, args: list[str]) -> str:
        if os.name != "nt":
            return "launch_failed"
        try:
            import ctypes
        except ImportError:
            return "launch_failed"

        cmdline = subprocess.list2cmdline(args)
        try:
            result = int(
                ctypes.windll.shell32.ShellExecuteW(
                    None,
                    "runas",
                    powershell_exe,
                    cmdline,
                    None,
                    0,
                )
            )
        except Exception:
            return "launch_failed"

        if result > 32:
            return "ok"
        if result == 5:
            return "elevation_denied"
        return "launch_failed"

    @staticmethod
    def _resolve_powershell_executable() -> str:
        if os.name != "nt":
            return ""
        candidates = []
        system_root = os.getenv("SystemRoot", "").strip()
        if system_root:
            candidates.append(
                Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
            )
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        found = shutil.which("powershell")
        if found:
            return found
        found = shutil.which("pwsh")
        if found:
            return found
        return ""

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

    def _fetch_release_payload(self, url: str) -> dict[str, object] | list[object] | None:
        etag = ""
        cached_payload: dict[str, object] | list[object] | None = None
        if self.cache_dir is not None:
            etag, cached_payload = self._read_cached_payload(url)

        payload, state, next_etag = self._fetch_json_with_etag(url, etag=etag)
        if state == "ok":
            if self.cache_dir is not None and isinstance(payload, (dict, list)):
                self._write_cached_payload(url, payload, next_etag)
            return payload

        if state == "not_modified" and isinstance(cached_payload, (dict, list)):
            return cached_payload
        if state == "error" and isinstance(cached_payload, (dict, list)):
            return cached_payload
        return None

    def _read_cached_payload(self, url: str) -> tuple[str, dict[str, object] | list[object] | None]:
        if self.cache_dir is None:
            return "", None

        cache_file = self._cache_file_for_url(url)
        if not cache_file.exists():
            return "", None

        try:
            raw = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "", None
        if not isinstance(raw, dict):
            return "", None

        etag = str(raw.get("etag", "")).strip()
        payload = raw.get("payload")
        if isinstance(payload, (dict, list)):
            return etag, payload
        return etag, None

    def _write_cached_payload(
        self,
        url: str,
        payload: dict[str, object] | list[object],
        etag: str,
    ) -> None:
        if self.cache_dir is None:
            return

        cache_file = self._cache_file_for_url(url)
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps(
                    {
                        "etag": etag,
                        "saved_at": int(time.time()),
                        "payload": payload,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            return

    def _cache_file_for_url(self, url: str) -> Path:
        if self.cache_dir is None:
            raise RuntimeError("cache_disabled")
        token = hashlib.sha1(url.encode("utf-8", errors="replace")).hexdigest()
        return self.cache_dir / f"release_{token}.json"

    @staticmethod
    def _fetch_json(url: str) -> dict[str, object] | list[object] | None:
        payload, state, _ = UpdateManager._fetch_json_with_etag(url, etag="")
        if state == "ok":
            return payload
        return None

    @staticmethod
    def _fetch_json_with_etag(
        url: str,
        etag: str = "",
    ) -> tuple[dict[str, object] | list[object] | None, str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Gethes-Updater/{__version__}",
        }
        if etag:
            headers["If-None-Match"] = etag

        req = request.Request(
            url,
            headers=headers,
            method="GET",
        )

        try:
            with request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                raw = resp.read()
                next_etag = str(resp.headers.get("ETag", "")).strip()
        except error.HTTPError as exc:
            if exc.code == 304:
                return None, "not_modified", etag
            return None, "error", ""
        except (error.URLError, TimeoutError, ValueError):
            return None, "error", ""

        if not raw:
            return None, "error", next_etag

        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None, "error", next_etag

        if isinstance(payload, (dict, list)):
            return payload, "ok", next_etag
        return None, "error", next_etag

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
    def _pick_portable_asset(raw_assets: object) -> dict[str, str] | None:
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
            if not lower.endswith(".zip"):
                continue

            score = 0
            if "portable" in lower or "win64" in lower:
                score += 4
            if "setup" in lower or "installer" in lower:
                score -= 3
            if "gethes" in lower:
                score += 2

            scored.append((score, {"name": name, "url": url}))

        if not scored:
            return None
        scored.sort(key=lambda row: row[0], reverse=True)
        return scored[0][1]

    @staticmethod
    def _pick_checksum_asset(raw_assets: object) -> dict[str, str] | None:
        if not isinstance(raw_assets, list):
            return None
        for item in raw_assets:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            url = str(item.get("url", "")).strip()
            if not name or not url:
                continue
            lower = name.lower()
            if lower.startswith("sha256sums") and (
                lower.endswith(".txt") or lower.endswith(".sha256") or "." not in lower
            ):
                return {"name": name, "url": url}
        return None

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
        if cleaned and "." in cleaned and not cleaned.endswith("."):
            return cleaned
        return f"{cleaned}.bin"

    @staticmethod
    def _safe_remove(path: Path) -> None:
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            return

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as fh:
                while True:
                    chunk = fh.read(1024 * 128)
                    if not chunk:
                        break
                    digest.update(chunk)
        except OSError:
            return ""
        return digest.hexdigest()

    @staticmethod
    def _parse_checksum_from_text(content: str, target_name: str) -> str:
        target = target_name.strip().lower()
        if not target:
            return ""

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            plain_match = re.match(r"^([A-Fa-f0-9]{64})\s+\*?(.+)$", line)
            if plain_match:
                checksum = plain_match.group(1)
                name = plain_match.group(2).strip().strip("\"'").replace("\\", "/")
                if Path(name).name.lower() == target:
                    return checksum

            openssl_match = re.match(r"^SHA256\s*\((.+)\)\s*=\s*([A-Fa-f0-9]{64})$", line)
            if openssl_match:
                name = openssl_match.group(1).strip().strip("\"'").replace("\\", "/")
                if Path(name).name.lower() == target:
                    return openssl_match.group(2)
        return ""
