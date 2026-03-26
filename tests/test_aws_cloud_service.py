from backend.aws_cloud_service import AwsSqliteTelemetryStore


def test_aws_store_heartbeat_and_presence(tmp_path) -> None:
    store = AwsSqliteTelemetryStore(tmp_path / "aws_telemetry.db", online_window_seconds=120)
    try:
        payload = {
            "install_id": "abcd1234efgh5678",
            "player_name": "Orion",
            "version": "0.06",
            "profile": {
                "slot_id": 1,
                "route_name": "Route 1",
                "story_page": 3,
                "story_total": 12,
                "achievements_unlocked": 4,
                "achievements_total": 18,
            },
            "scores": {
                "snake_best_score": 42,
                "snake_best_level": 3,
                "snake_longest_length": 11,
                "rogue_best_depth": 6,
                "rogue_best_gold": 300,
                "rogue_best_kills": 9,
                "rogue_runs": 4,
                "rogue_wins": 1,
            },
            "preferences": {
                "graphics": "high",
                "language_active": "es",
                "ui_scale": 1.2,
                "theme": "obsidian",
            },
            "syster": {
                "mode": "hybrid",
                "core_enabled": True,
                "model": "mistral",
                "training": {
                    "overview": {
                        "interactions": 20,
                        "feedback": 7,
                        "long_memory": 5,
                        "events": 4,
                        "commands": 8,
                        "snapshots": 2,
                    },
                    "feedback_avg_score": 0.77,
                    "feedback_positive": 5,
                    "feedback_negative": 1,
                    "feedback_samples": [
                        {
                            "local_id": 11,
                            "ts": 1772688000,
                            "score": 1.0,
                            "notes": "auto:player",
                            "prompt": "hola",
                            "reply": "hola orion",
                        }
                    ],
                    "memory_top": [{"key": "persona_tone", "value": "melancolico"}],
                    "intent_top": [{"intent": "story", "count": 12}],
                },
            },
        }

        result = store.heartbeat(payload)
        assert result["ok"] is True
        assert int(result["registered_users"]) == 1
        assert int(result["players_online"]) >= 1
        assert int(result["syster_feedback_ingested"]) == 1
        assert bool(result["syster_profile_synced"]) is True

        online, users = store.presence()
        assert users == 1
        assert online >= 1

        summary = store.syster_global_summary()
        assert int(summary["samples"]) == 1
        assert float(summary["avg_score"]) >= 0.9
    finally:
        store.close()


def test_aws_store_auth_and_news(tmp_path) -> None:
    store = AwsSqliteTelemetryStore(tmp_path / "aws_auth.db", online_window_seconds=120)
    try:
        result = store.register_user(
            username="orion_dev",
            email="orion@example.com",
            password="secretpass123",
            install_id="abcd1234efgh5678",
        )
        assert result["ok"] is True
        token = str(result["session_token"])
        assert token

        me = store.resolve_session_user(token)
        assert me is not None
        assert str(me["username"]) == "orion_dev"

        login = store.login_user(
            login="orion@example.com",
            password="secretpass123",
            install_id="abcd1234efgh5678",
        )
        assert login["ok"] is True

        # Avoid network dependency in test.
        store.refresh_news_from_github = lambda repo="": {"inserted": 0, "repo": 1}  # type: ignore[method-assign]
        store._insert_news_item(
            item_key="release:v0.99",
            source_type="release",
            title="Release v0.99",
            summary="Major cloud update",
            source_url="https://example.com/release",
            published_at=1772688000.0,
        )
        feed = store.fetch_news_for_user(session_token=token, limit=5, mark_seen=False)
        assert feed["ok"] is True
        assert int(feed["unread"]) >= 1
        assert isinstance(feed["items"], list)
        assert feed["items"]

        assert store.logout_session(token) is True
        assert store.resolve_session_user(token) is None
    finally:
        store.close()
