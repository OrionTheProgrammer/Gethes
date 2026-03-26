# Gethes Cloud Sync (Player DB Link)

This document defines the cloud contract used by the `cloud` command.

## Goal

Allow Gethes clients to sync:
- current players (presence/online),
- player usernames,
- best scores (`snake`, `roguelike`),
- user preferences (graphics, language, UI scale, theme),
- Syster training summary and recent feedback samples.

## Client commands

- `cloud status`
- `cloud link <https://api.your-server> [api_key]`
- `cloud key <token|off>`
- `cloud sync`
- `cloud online`
- `cloud off`

## HTTP contract

Base URL:
- `https://api.your-server`

Heartbeat endpoint:
- `POST /v1/telemetry/heartbeat`

Presence endpoint:
- `GET /v1/telemetry/presence`

### Heartbeat request body

```json
{
  "install_id": "8cf2660df3524f7abf0d32eb7c44ef6b",
  "player_name": "Orion",
  "reason": "manual_sync",
  "version": "0.08",
  "timestamp_unix": 1772688000,
  "profile": {
    "slot_id": 1,
    "route_name": "Route 1",
    "story_page": 6,
    "story_total": 18,
    "achievements_unlocked": 7,
    "achievements_total": 18
  },
  "scores": {
    "snake_best_score": 180,
    "snake_best_level": 5,
    "snake_longest_length": 21,
    "rogue_best_depth": 4,
    "rogue_best_gold": 325,
    "rogue_best_kills": 12,
    "rogue_runs": 8,
    "rogue_wins": 2
  },
  "preferences": {
    "language_mode": "auto",
    "language_active": "es",
    "graphics": "high",
    "sound": true,
    "ui_scale": 1.1,
    "theme": "abyss_protocol",
    "theme_fx": {
      "scan": 1.18,
      "glow": 1.22,
      "particles": 1.2
    }
  },
  "syster": {
    "mode": "hybrid",
    "core_enabled": true,
    "model": "mistral",
    "training": {
      "overview": {
        "interactions": 2400,
        "feedback": 980,
        "long_memory": 9,
        "events": 412,
        "commands": 338,
        "snapshots": 47
      },
      "feedback_avg_score": 0.79,
      "feedback_positive": 730,
      "feedback_negative": 58,
      "feedback_samples": [
        {
          "local_id": 1732,
          "ts": 1772688123.0,
          "score": 1.0,
          "notes": "auto:player",
          "prompt": "Estoy bloqueado en historia, dame una pista.",
          "reply": "Busca el archivo roto antes de abrir la puerta principal."
        }
      ],
      "memory_top": [
        {
          "key": "persona_tone",
          "value": "melancolico, preciso, inmersivo, empatico",
          "weight": 3.3,
          "source": "curriculum"
        }
      ],
      "intent_top": [
        {"intent": "story", "count": 125},
        {"intent": "rogue", "count": 93}
      ]
    }
  }
}
```

### Expected response

```json
{
  "ok": true,
  "message": "synced",
  "players_online": 14,
  "registered_users": 112,
  "syster_profile_synced": true,
  "syster_feedback_ingested": 6,
  "syster_global_samples": 4280,
  "syster_global_avg_score": 0.77
}
```

### Presence response

```json
{
  "players_online": 14,
  "registered_users": 112,
  "syster_global_samples": 4280,
  "syster_global_avg_score": 0.77
}
```

## Extra Oracle tables

The Oracle backend now maintains:
- `GETHES_TELEMETRY_PLAYERS`
- `GETHES_SYSTER_PROFILE`
- `GETHES_SYSTER_FEEDBACK`

## Minimal DB model (SQL)

```sql
create table if not exists players (
  install_id text primary key,
  player_name text not null,
  version text not null,
  last_seen timestamptz not null default now(),
  slot_id int not null default 1,
  route_name text not null default 'Route 1',
  snake_best_score int not null default 0,
  snake_best_level int not null default 0,
  rogue_best_depth int not null default 0,
  rogue_best_gold int not null default 0,
  rogue_best_kills int not null default 0,
  graphics text not null default 'medium',
  language_active text not null default 'en',
  ui_scale numeric not null default 1.0,
  theme text not null default 'obsidian'
);
```

## Online players rule

Recommended rule:
- `players_online = count(*) where last_seen > now() - interval '2 minutes'`

## Security

- Use HTTPS only.
- Validate `Authorization: Bearer <token>` (or `X-API-Key`).
- Apply rate limit per `install_id` and per IP.
