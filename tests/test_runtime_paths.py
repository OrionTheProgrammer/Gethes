from pathlib import Path

from gethes import runtime_paths


def test_user_data_dir_prefers_platformdirs_when_available(monkeypatch, tmp_path: Path) -> None:
    expected = tmp_path / "PlatformData" / "Gethes"

    monkeypatch.setattr(
        runtime_paths,
        "_platform_user_data_dir",
        lambda appname, appauthor=False, roaming=True: str(expected),
    )

    path = runtime_paths.user_data_dir("Gethes")
    assert path == expected
    assert path.exists()


def test_user_data_dir_falls_back_to_appdata_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runtime_paths, "_platform_user_data_dir", None)
    appdata = tmp_path / "AppData"
    monkeypatch.setenv("APPDATA", str(appdata))

    path = runtime_paths.user_data_dir("Gethes")
    assert path == appdata / "Gethes"
    assert path.exists()
