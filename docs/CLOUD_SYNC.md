# Gethes Cloud Sync Contract

This document defines the cloud sync contract used by Gethes clients and backend services.

## Scope

Cloud sync is used to persist and aggregate:

- player identity and install-level telemetry,
- save/profile metadata and best scores,
- player preferences (graphics, language, UI scale, theme),
- Syster training summary and feedback samples,
- authenticated account sessions,
- release/commit news feed for registered users.

## In-Game Commands

### Cloud Core

- `cloud status`
- `cloud link <http(s)://host[:port]> [api_key]`
- `cloud key <token|off>`
- `cloud sync`
- `cloud online`
- `cloud interval <20-600>`
- `cloud news [count]`
- `cloud newsinterval <60-3600>`
- `cloud off`

### Account / Auth

- `auth status`
- `auth setup`
- `auth register <username> <email> <password>`
- `auth login <username|email> <password>`
- `auth me`
- `auth logout`

## Base URL

Example:

- `http://ec2-44-205-252-139.compute-1.amazonaws.com:443`

## HTTP Endpoints

- `GET /health`
- `POST /v1/telemetry/heartbeat`
- `GET /v1/telemetry/presence`
- `POST /v1/auth/register`
- `POST /v1/auth/login`
- `POST /v1/auth/logout`
- `GET /v1/auth/me`
- `GET /v1/news`

## Authentication Layers

1. **Backend API key** (optional):  
   Use `Authorization: Bearer <api_key>` or `X-API-Key: <api_key>`.

2. **User session token** (required for account/news endpoints):  
   Use `X-Gethes-Session: <session_token>`.

Heartbeat can be called without a user session, but when session is present the backend can bind telemetry to the authenticated user.

## Heartbeat Request Example

```json
{
  "install_id": "8cf2660df3524f7abf0d32eb7c44ef6b",
  "player_name": "Orion",
  "reason": "autosync",
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
    "language_active": "en",
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
    "mode": "local",
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
      "feedback_negative": 58
    }
  },
  "auth_user": {
    "username": "orion",
    "email": "orion@example.com"
  }
}
```

## Heartbeat Response Example

```json
{
  "ok": true,
  "message": "synced",
  "players_online": 14,
  "registered_users": 112,
  "syster_profile_synced": true,
  "syster_feedback_ingested": 6,
  "syster_global_samples": 4280,
  "syster_global_avg_score": 0.77,
  "server_time_utc": "2026-03-26T22:00:00Z"
}
```

## Presence Response Example

```json
{
  "players_online": 14,
  "registered_users": 112,
  "syster_global_samples": 4280,
  "syster_global_avg_score": 0.77
}
```

## Auth Contract (High Level)

### Register

`POST /v1/auth/register`

Body:

```json
{
  "username": "orion",
  "email": "orion@example.com",
  "password": "StrongPass123",
  "install_id": "8cf2660df3524f7abf0d32eb7c44ef6b"
}
```

Returns session token on success.

### Login

`POST /v1/auth/login`

Body:

```json
{
  "login": "orion@example.com",
  "password": "StrongPass123",
  "install_id": "8cf2660df3524f7abf0d32eb7c44ef6b"
}
```

Returns session token on success.

### Me

`GET /v1/auth/me`  
Headers: `X-Gethes-Session`

### Logout

`POST /v1/auth/logout`  
Headers: `X-Gethes-Session`

## News Feed Contract (High Level)

`GET /v1/news?limit=8&mark_seen=0&repo=OrionTheProgrammer/Gethes`  
Headers: `X-Gethes-Session`

News items are sourced from:

- latest GitHub release,
- latest repository commits.

## Recommended Security

- Use HTTPS in production whenever possible.
- Keep API key in a server-only secret store.
- Apply request throttling by `install_id` and by IP.
- Rotate keys/tokens periodically.
