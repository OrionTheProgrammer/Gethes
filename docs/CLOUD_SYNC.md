# Gethes Cloud Sync (Player DB Link)

This document defines the cloud contract used by the `cloud` command.

## Goal

Allow Gethes clients to sync:
- current players (presence/online),
- player usernames,
- best scores (`snake`, `roguelike`),
- user preferences (graphics, language, UI scale, theme).

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
  "version": "0.05",
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
  }
}
```

### Expected response

```json
{
  "ok": true,
  "message": "synced",
  "players_online": 14,
  "registered_users": 112
}
```

### Presence response

```json
{
  "players_online": 14,
  "registered_users": 112
}
```

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
