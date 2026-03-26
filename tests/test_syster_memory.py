import sqlite3

from gethes.syster import SysterAssistant, SysterContext
from gethes.syster_memory import SysterKnowledgeStore


def test_observe_exchange_persists_training_and_memory(tmp_path) -> None:
    store = SysterKnowledgeStore(tmp_path / "syster")
    try:
        syster = SysterAssistant(mode="local", knowledge_store=store)
        context = SysterContext(
            player_name="Orion",
            route_name="Route 2",
            language="es",
            active_theme="obsidian",
            best_scores={"snake_best_score": 133},
        )

        syster.observe_exchange(
            prompt="hola",
            reply="conexion establecida",
            context=context,
            source="player",
            intent="greet",
        )
        syster.record_feedback(
            prompt="hola",
            reply="conexion establecida",
            score=0.9,
            notes="manual_positive",
        )
        store.set_preference("cloud_last_sync", "123")

        conn = sqlite3.connect(store.training_db_path)
        try:
            interactions = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
            long_memory = conn.execute("SELECT COUNT(*) FROM long_memory").fetchone()[0]
        finally:
            conn.close()

        assert interactions >= 2
        assert long_memory >= 3

        overview = store.get_training_overview()
        assert overview["interactions"] >= 2
        assert overview["feedback"] >= 1
        assert overview["long_memory"] >= 3

        memories = store.get_long_memory_entries(limit=4, min_weight=0.0)
        assert memories

        feedback = store.get_feedback_examples(limit=2, min_score=0.5)
        assert feedback
        cloud_payload = store.get_cloud_training_payload(feedback_limit=3, memory_limit=3)
        assert "overview" in cloud_payload
        assert cloud_payload["overview"]["feedback"] >= 1
        assert isinstance(cloud_payload["feedback_samples"], list)
        assert cloud_payload["feedback_samples"]
        assert store.get_preference("cloud_last_sync") == "123"
        assert store.get_preference("missing_key", "fallback") == "fallback"

        assert store.delete_long_memory("player_name") is True
        assert store.delete_long_memory("player_name") is False
    finally:
        store.close()

