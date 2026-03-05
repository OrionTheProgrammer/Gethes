from gethes.updater import UpdateManager


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
