from pathlib import Path

from gethes.cloud_sync import CloudSyncClient
from gethes.config import ConfigStore, GameConfig


def test_cloud_endpoint_normalization() -> None:
    assert (
        CloudSyncClient.normalize_endpoint("https://api.example.com/v1/telemetry/")
        == "https://api.example.com"
    )
    assert (
        CloudSyncClient.normalize_endpoint("https://api.example.com/")
        == "https://api.example.com"
    )


def test_cloud_masked_key() -> None:
    client = CloudSyncClient("https://api.example.com", api_key="abcdef1234567890")
    assert client.masked_key() == "abcd...7890"


def test_cloud_not_linked_returns_safe_status() -> None:
    client = CloudSyncClient("")
    response = client.push_snapshot({"player_name": "A"})
    assert response.ok is False
    assert response.message == "not_linked"


def test_config_store_roundtrip_cloud_and_player(tmp_path: Path) -> None:
    path = tmp_path / "cfg.json"
    store = ConfigStore(path)
    cfg = GameConfig()
    cfg.player_name = "Orion"
    cfg.cloud_endpoint = "https://api.example.com"
    cfg.cloud_api_key = "token_123"
    cfg.cloud_enabled = True
    store.save(cfg)

    loaded = store.load()
    assert loaded.player_name == "Orion"
    assert loaded.cloud_endpoint == "https://api.example.com"
    assert loaded.cloud_api_key == "token_123"
    assert loaded.cloud_enabled is True
    assert len(loaded.install_id) == 32
