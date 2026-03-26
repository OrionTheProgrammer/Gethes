from gethes.syster import SysterAssistant, SysterContext
from gethes.syster_memory import SysterKnowledgeStore


def _tr(key: str, **_kwargs: object) -> str:
    return key


def test_syster_runtime_is_locked_to_local_mistral() -> None:
    syster = SysterAssistant(mode="off", ollama_enabled=False, ollama_model="llama3")
    assert syster.mode == "local"
    assert syster.ollama_enabled is True
    assert syster.ollama_model == "mistral"
    assert syster.set_mode("hybrid") is False
    syster.set_ollama_enabled(False)
    syster.set_ollama_model("qwen")
    assert syster.ollama_enabled is True
    assert syster.ollama_model == "mistral"


def test_ollama_host_is_normalized() -> None:
    syster = SysterAssistant(
        mode="local",
        ollama_enabled=True,
        ollama_host="127.0.0.1:11434",
    )
    assert syster.ollama_host == "http://127.0.0.1:11434"


def test_reply_uses_ollama_when_available(monkeypatch) -> None:
    syster = SysterAssistant(
        mode="local",
        ollama_enabled=True,
        ollama_model="mistral",
        ollama_host="http://127.0.0.1:11434",
    )
    ctx = SysterContext(last_command="menu")

    monkeypatch.setattr(syster, "_probe_ollama", lambda force=False: (True, "online"))
    monkeypatch.setattr(syster, "_ollama_reply_httpx", lambda payload: "respuesta llm")

    reply = syster.reply("hola syster", _tr, ctx)
    assert reply == "respuesta llm"


def test_reply_falls_back_when_ollama_unavailable(monkeypatch) -> None:
    syster = SysterAssistant(
        mode="local",
        ollama_enabled=True,
        ollama_model="mistral",
        ollama_host="http://127.0.0.1:11434",
    )
    ctx = SysterContext(last_command="menu")

    monkeypatch.setattr(syster, "_probe_ollama", lambda force=False: (False, "offline"))

    reply = syster.reply("necesito ayuda", _tr, ctx)
    assert reply == "app.syster.reply.help"


def test_extract_control_command_parses_marker() -> None:
    raw = "[[sys:theme deepsea]]\nPerfecto, aplicando una atmosfera fria."
    command, text = SysterAssistant.extract_control_command(raw)
    assert command == "theme deepsea"
    assert text == "Perfecto, aplicando una atmosfera fria."


def test_build_payload_includes_long_memory(tmp_path) -> None:
    store = SysterKnowledgeStore(tmp_path / "syster")
    try:
        store.upsert_long_memory("player_name", "Orion", weight=2.0, source="test")
        store.record_feedback("hola", "hola", 0.8, "positive")
        syster = SysterAssistant(
            mode="local",
            ollama_enabled=True,
            knowledge_store=store,
        )
        ctx = SysterContext(player_name="Orion", language="es")
        payload = syster._build_ollama_payload("hola", ctx)
        prompt = str(payload.get("prompt", ""))
        assert "Long memory:" in prompt
        assert "Training feedback:" in prompt
    finally:
        store.close()


def test_optimize_for_cuda_profile_quality_sets_expected_values() -> None:
    syster = SysterAssistant(mode="local", ollama_enabled=True)
    result = syster.optimize_for_cuda("quality")
    assert result["profile"] == "quality"
    assert syster.ollama_context_length == 8192
    assert syster.ollama_kv_cache_type == "f16"
    assert syster.ollama_flash_attention is True


def test_runtime_env_contains_cuda_tuning_defaults() -> None:
    syster = SysterAssistant(mode="local", ollama_enabled=True)
    env = syster._ollama_runtime_env()
    assert env["OLLAMA_CONTEXT_LENGTH"] == str(syster.ollama_context_length)
    assert env["OLLAMA_FLASH_ATTENTION"] in {"0", "1"}
    assert env["OLLAMA_KV_CACHE_TYPE"] in {"f16", "q8_0", "q4_0"}


