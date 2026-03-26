from __future__ import annotations

import json

from gethes.config import ConfigStore, GameConfig


def test_game_config_defaults_enable_real_syster_ai() -> None:
    cfg = GameConfig()
    assert cfg.syster_mode == "local"
    assert cfg.syster_ollama_enabled is True
    assert cfg.syster_ollama_model == "mistral"


def test_legacy_modes_are_migrated_to_local_and_mistral(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "syster_mode": "lite",
                "syster_endpoint": "https://example.invalid/syster",
                "syster_ollama_model": "llama3",
                "syster_ollama_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    cfg = ConfigStore(path).load()
    assert cfg.syster_mode == "local"
    assert cfg.syster_endpoint == ""
    assert cfg.syster_ollama_enabled is True
    assert cfg.syster_ollama_model == "mistral"


def test_persisted_syster_values_are_hardened_to_runtime_invariants(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "syster_mode": "off",
                "syster_mode_user_set": True,
                "syster_endpoint": "https://example.invalid/remote",
                "syster_ollama_enabled": False,
                "syster_ollama_model": "qwen2.5",
            }
        ),
        encoding="utf-8",
    )
    cfg = ConfigStore(path).load()
    assert cfg.syster_mode == "local"
    assert cfg.syster_mode_user_set is True
    assert cfg.syster_endpoint == ""
    assert cfg.syster_ollama_enabled is True
    assert cfg.syster_ollama_model == "mistral"
