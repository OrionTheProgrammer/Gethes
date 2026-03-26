# Oracle Backend Setup for Gethes

This backend connects Gethes cloud telemetry to Oracle Autonomous Database using your wallet.

If your infrastructure is pure AWS (EC2) and you do not need Oracle ADB, use:
- [AWS_BACKEND_SETUP.md](AWS_BACKEND_SETUP.md)

## 1) Install backend dependency

```powershell
pip install -r backend/requirements.txt
```

## 2) Check DSN aliases from your wallet

```powershell
python backend/oracle_cloud_service.py `
  --wallet-zip "C:\Users\orion\Downloads\Wallet_Gethes.zip" `
  --list-dsn
```

Expected aliases in your wallet:
- `gethes_high`
- `gethes_medium`
- `gethes_low`
- `gethes_tp`
- `gethes_tpurgent`

## 3) Start Oracle telemetry backend

Quick start script (recommended):

```powershell
$env:GETHES_ORACLE_USER="ADMIN"
$env:GETHES_ORACLE_PASSWORD="<ORACLE_DB_PASSWORD>"
.\backend\start_oracle_backend.ps1
```

Or run manually:

```powershell
python backend/oracle_cloud_service.py `
  --wallet-zip "C:\Users\orion\Downloads\Wallet_Gethes.zip" `
  --wallet-dir ".wallet_oracle_gethes" `
  --dsn "gethes_high" `
  --db-user "<ORACLE_DB_USER>" `
  --db-password "<ORACLE_DB_PASSWORD>" `
  --tcp-connect-timeout 6 `
  --retry-count 1 `
  --retry-delay 1 `
  --host "127.0.0.1" `
  --port 8787 `
  --api-key "<OPTIONAL_API_KEY>"
```

If your wallet requires password, add:

```powershell
--wallet-password "<WALLET_PASSWORD>"
```

If startup takes too long, lower retries further:

```powershell
--retry-count 0 --tcp-connect-timeout 4
```

Linux server deployment with SSH key:
- See [LINUX_BACKEND_DEPLOY.md](LINUX_BACKEND_DEPLOY.md)

## 4) Link Gethes client to backend

Inside Gethes:

```text
cloud link http://127.0.0.1:8787 <OPTIONAL_API_KEY>
cloud sync
cloud online
```

## 5) What is stored

Table created automatically:
- `GETHES_TELEMETRY_PLAYERS`
- `GETHES_SYSTER_PROFILE`
- `GETHES_SYSTER_FEEDBACK`

Stored fields include:
- user identity (`install_id`, `player_name`)
- presence (`last_seen`)
- Snake best stats
- Roguelike best stats
- profile progress and preferences
- Syster training overview and model mode metadata
- Recent Syster feedback samples (`prompt/reply/score/notes`) for incremental learning

## 6) Online player logic

Presence counts:
- `players_online`: users seen in the last 120 seconds
- `registered_users`: total known players

You can adjust the window using:

```powershell
--online-window-seconds 180
```
