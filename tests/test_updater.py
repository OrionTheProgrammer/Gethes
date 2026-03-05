import os
from pathlib import Path
import time

from gethes.updater import UpdateInfo, UpdateManager


def _make_update_info(installer_name: str = "", portable_name: str = "") -> UpdateInfo:
    return UpdateInfo(
        repo="OrionTheProgrammer/Gethes",
        current_version="0.3.0",
        latest_version="0.4.0",
        tag_name="v0.4.0",
        release_name="v0.4.0",
        html_url="https://example.invalid/release",
        release_notes="",
        installer_name=installer_name,
        installer_url=("https://example.invalid/setup.exe" if installer_name else ""),
        portable_name=portable_name,
        portable_url=("https://example.invalid/portable.zip" if portable_name else ""),
        checksum_name="",
        checksum_url="",
    )


def test_normalize_repo_accepts_github_url() -> None:
    assert (
        UpdateManager._normalize_repo("https://github.com/OrionTheProgrammer/Gethes")
        == "OrionTheProgrammer/Gethes"
    )


def test_normalize_repo_rejects_invalid_repo() -> None:
    assert UpdateManager._normalize_repo("bad/repo/extra") == ""
    assert UpdateManager._normalize_repo("owner only") == ""


def test_compare_versions() -> None:
    assert UpdateManager._compare_versions("0.2.0", "0.1.9") == 1
    assert UpdateManager._compare_versions("0.2.0", "0.2.0") == 0
    assert UpdateManager._compare_versions("0.2.0", "0.2.1") == -1


def test_pick_assets_prefers_setup_and_portable_zip() -> None:
    assets = [
        {"name": "Gethes-v0.02-win64-portable.zip", "url": "portable"},
        {"name": "Gethes-Setup-v0.02.exe", "url": "setup"},
        {"name": "random.exe", "url": "random"},
    ]
    installer = UpdateManager._pick_installer_asset(assets)
    portable = UpdateManager._pick_portable_asset(assets)
    assert installer is not None
    assert portable is not None
    assert installer["url"] == "setup"
    assert portable["url"] == "portable"


def test_pick_checksum_asset() -> None:
    assets = [
        {"name": "notes.md", "url": "n"},
        {"name": "SHA256SUMS-v0.03.txt", "url": "sha"},
    ]
    checksum = UpdateManager._pick_checksum_asset(assets)
    assert checksum is not None
    assert checksum["url"] == "sha"


def test_parse_checksum_from_text_supports_common_formats() -> None:
    content = "\n".join(
        [
            "abc",
            "f0c526b259a4e5aa8bd80890af04f1e4b058710f086640918b1bb08f15382386  Gethes-Setup-v0.03.exe",
            "SHA256 (Gethes-v0.03-win64-portable.zip) = c3b1966de224f03914f6c3e20de62b0dd9f8946724ec22abc158756eba8402dc",
        ]
    )
    setup_sum = UpdateManager._parse_checksum_from_text(content, "Gethes-Setup-v0.03.exe")
    zip_sum = UpdateManager._parse_checksum_from_text(
        content, "Gethes-v0.03-win64-portable.zip"
    )
    assert setup_sum == "f0c526b259a4e5aa8bd80890af04f1e4b058710f086640918b1bb08f15382386"
    assert zip_sum == "c3b1966de224f03914f6c3e20de62b0dd9f8946724ec22abc158756eba8402dc"


def test_can_portable_update_uses_elevation_when_direct_write_is_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    manager = UpdateManager(current_version="0.3.0", repo="OrionTheProgrammer/Gethes")

    monkeypatch.setattr(UpdateManager, "can_self_update_portable", lambda self, path: False)
    monkeypatch.setattr(
        UpdateManager,
        "_supports_elevated_portable_update",
        lambda self, path: True,
    )

    assert manager.can_portable_update(app_dir) is True


def test_launch_portable_self_update_reports_elevation_denied(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manager = UpdateManager(current_version="0.3.0", repo="OrionTheProgrammer/Gethes")
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    zip_path = tmp_path / "Gethes-v0.03-win64-portable.zip"
    zip_path.write_bytes(b"dummy")
    exe_path = app_dir / "Gethes.exe"
    exe_path.write_bytes(b"dummy")
    working_dir = tmp_path / "updates"

    monkeypatch.setattr(UpdateManager, "can_self_update_portable", lambda self, path: False)
    monkeypatch.setattr(
        UpdateManager,
        "_supports_elevated_portable_update",
        lambda self, path: True,
    )
    monkeypatch.setattr(
        UpdateManager,
        "_resolve_powershell_executable",
        staticmethod(lambda: "powershell.exe"),
    )
    monkeypatch.setattr(
        UpdateManager,
        "_launch_powershell_process",
        lambda self, exe, args, elevated: "elevation_denied",
    )

    status = manager.launch_portable_self_update(
        zip_path=zip_path,
        app_dir=app_dir,
        exe_path=exe_path,
        working_dir=working_dir,
    )
    assert status == "elevation_denied"


def test_check_latest_uses_cache_when_etag_not_modified(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    manager = UpdateManager(
        current_version="0.1.0",
        repo="OrionTheProgrammer/Gethes",
        cache_dir=cache_dir,
    )
    url = "https://api.github.com/repos/OrionTheProgrammer/Gethes/releases/latest"
    cached_payload = {
        "tag_name": "v0.2.0",
        "name": "v0.2.0",
        "html_url": "https://example.invalid/release",
        "assets": [{"name": "Gethes-Setup-v0.2.0.exe", "url": "asset-url"}],
    }
    manager._write_cached_payload(url, cached_payload, '"etag123"')

    monkeypatch.setattr(
        UpdateManager,
        "_fetch_json_with_etag",
        staticmethod(lambda _url, etag="": (None, "not_modified", etag)),
    )

    status, info = manager.check_latest()
    assert status == "available"
    assert info is not None
    assert info.latest_version == "0.2.0"


def test_check_latest_uses_cache_when_network_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    manager = UpdateManager(
        current_version="0.1.0",
        repo="OrionTheProgrammer/Gethes",
        cache_dir=cache_dir,
    )
    url = "https://api.github.com/repos/OrionTheProgrammer/Gethes/releases/latest"
    cached_payload = {
        "tag_name": "v0.2.1",
        "name": "v0.2.1",
        "html_url": "https://example.invalid/release",
        "assets": [{"name": "Gethes-v0.2.1-win64-portable.zip", "url": "asset-url"}],
    }
    manager._write_cached_payload(url, cached_payload, "")

    monkeypatch.setattr(
        UpdateManager,
        "_fetch_json_with_etag",
        staticmethod(lambda _url, etag="": (None, "error", "")),
    )

    status, info = manager.check_latest()
    assert status == "available"
    assert info is not None
    assert info.latest_version == "0.2.1"


def test_cleanup_update_artifacts_removes_old_files(tmp_path: Path) -> None:
    manager = UpdateManager(current_version="0.3.0", repo="OrionTheProgrammer/Gethes")
    updates_dir = tmp_path / "updates"
    updates_dir.mkdir()

    stale_zip = updates_dir / "Gethes-v0.01-win64-portable.zip"
    stale_zip.write_bytes(b"stale")
    old_time = time.time() - (60 * 86400)
    os.utime(stale_zip, (old_time, old_time))

    recent_zip = updates_dir / "Gethes-v0.03-win64-portable.zip"
    recent_zip.write_bytes(b"recent")

    stale_tmp_dir = updates_dir / "_update_tmp_deadbeef"
    stale_tmp_dir.mkdir()

    manager.cleanup_update_artifacts(updates_dir, keep_recent=1, max_age_days=7)

    assert not stale_zip.exists()
    assert recent_zip.exists()
    assert not stale_tmp_dir.exists()


def test_verify_asset_checksum_requires_manifest_by_default(tmp_path: Path) -> None:
    manager = UpdateManager(current_version="0.3.0", repo="OrionTheProgrammer/Gethes")
    asset = tmp_path / "Gethes-Setup-v0.03.exe"
    asset.write_bytes(b"binary")
    update_info = _make_update_info(installer_name="Gethes-Setup-v0.04.exe")

    ok, status = manager.verify_asset_checksum(
        asset_path=asset,
        update=update_info,
        output_dir=tmp_path,
    )
    assert ok is False
    assert status == "checksum_missing_required"


def test_verify_asset_checksum_allows_missing_manifest_when_unsafe(tmp_path: Path) -> None:
    manager = UpdateManager(current_version="0.3.0", repo="OrionTheProgrammer/Gethes")
    asset = tmp_path / "Gethes-v0.03-win64-portable.zip"
    asset.write_bytes(b"binary")

    update_info = _make_update_info(portable_name="Gethes-v0.04-win64-portable.zip")

    ok, status = manager.verify_asset_checksum(
        asset_path=asset,
        update=update_info,
        output_dir=tmp_path,
        require_checksum=False,
    )
    assert ok is True
    assert status == "checksum_missing"


def test_find_cached_download_returns_existing_asset(tmp_path: Path) -> None:
    manager = UpdateManager(current_version="0.3.0", repo="OrionTheProgrammer/Gethes")
    update_info = _make_update_info(installer_name="Gethes Setup v0.04.exe")
    expected = manager.expected_download_path(update_info, tmp_path, "installer")
    assert expected is not None
    expected.write_bytes(b"cached")

    cached = manager.find_cached_download(update_info, tmp_path, "installer")
    assert cached == expected
