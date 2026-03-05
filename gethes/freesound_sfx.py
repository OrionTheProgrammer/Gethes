from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import freesound
except Exception:  # pragma: no cover - optional runtime dependency
    freesound = None


@dataclass(frozen=True)
class FreesoundSearchItem:
    sound_id: int
    name: str
    username: str
    duration: float
    license_name: str


class FreesoundSFXService:
    def __init__(self, api_key: str = "") -> None:
        self._api_key = ""
        self._client = freesound.FreesoundClient() if freesound is not None else None
        if api_key:
            self.set_api_key(api_key)

    def is_dependency_available(self) -> bool:
        return self._client is not None

    def is_configured(self) -> bool:
        return bool(self._api_key) and self._client is not None

    def set_api_key(self, api_key: str) -> bool:
        clean_key = api_key.strip()
        if not clean_key:
            self.clear_api_key()
            return True

        if self._client is None:
            return False

        try:
            self._client.set_token(clean_key, auth_type="token")
        except Exception:
            return False

        self._api_key = clean_key
        return True

    def clear_api_key(self) -> None:
        self._api_key = ""
        if self._client is None:
            return
        try:
            self._client.set_token("", auth_type="token")
        except Exception:
            return

    def masked_key(self) -> str:
        if not self._api_key:
            return "-"
        if len(self._api_key) <= 8:
            return "*" * len(self._api_key)
        return f"{self._api_key[:4]}...{self._api_key[-4:]}"

    def search(self, query: str, limit: int = 6) -> tuple[list[FreesoundSearchItem], str]:
        if self._client is None:
            return [], "dependency_missing"
        if not self._api_key:
            return [], "api_key_missing"

        clean_query = query.strip()
        if not clean_query:
            return [], "empty_query"

        page_size = max(1, min(12, int(limit)))
        try:
            results = self._client.search(
                query=clean_query,
                filter="duration:[0 TO 15]",
                sort="score",
                fields="id,name,username,duration,license,previews",
                page_size=page_size,
            )
        except Exception as exc:
            return [], str(exc)

        items: list[FreesoundSearchItem] = []
        for sound in results:
            try:
                items.append(
                    FreesoundSearchItem(
                        sound_id=int(getattr(sound, "id", 0)),
                        name=str(getattr(sound, "name", "")) or "unknown",
                        username=str(getattr(sound, "username", "")) or "unknown",
                        duration=float(getattr(sound, "duration", 0.0) or 0.0),
                        license_name=str(getattr(sound, "license", "")) or "-",
                    )
                )
            except Exception:
                continue

            if len(items) >= page_size:
                break

        return items, ""

    def download_preview(
        self,
        sound_id: int,
        output_dir: Path,
        target_name: str,
        quality: str = "lq",
        file_format: str = "ogg",
    ) -> tuple[Path | None, str]:
        if self._client is None:
            return None, "dependency_missing"
        if not self._api_key:
            return None, "api_key_missing"

        try:
            sid = int(sound_id)
        except (TypeError, ValueError):
            return None, "invalid_sound_id"
        if sid <= 0:
            return None, "invalid_sound_id"

        safe_name = Path(target_name).name.strip()
        if not safe_name:
            safe_name = f"sound_{sid}.{file_format}"

        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            sound = self._client.get_sound(sid)
            downloaded = sound.retrieve_preview(
                str(output_dir),
                name=safe_name,
                quality=quality,
                file_format=file_format,
            )
        except Exception as exc:
            return None, str(exc)

        return Path(downloaded), ""
