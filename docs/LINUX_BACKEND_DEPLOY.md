# Deploy Oracle Backend on Linux (SSH Key)

This script deploys the Oracle telemetry backend to a Linux server using SSH key auth and configures a `systemd` service.

Script:
- `tools/deploy_oracle_backend_linux.ps1`

## Requirements

- Windows machine with `ssh` and `scp` available.
- Linux server with `sudo` access.
- Oracle wallet zip file (optional upload by script).
- SSH private key file.

## Example

```powershell
.\tools\deploy_oracle_backend_linux.ps1 `
  -HostName "YOUR_SERVER_IP_OR_DOMAIN" `
  -User "ubuntu" `
  -SshKeyPath "C:\Users\orion\Downloads\ssh-key-2024-06-20.key" `
  -LocalWalletZipPath "C:\Users\orion\Downloads\Wallet_Gethes.zip" `
  -Dsn "gethes_high" `
  -DbUser "ADMIN" `
  -DbPassword "<ORACLE_DB_PASSWORD>" `
  -WalletPassword "<WALLET_PASSWORD_IF_REQUIRED>" `
  -ApiKey "<OPTIONAL_API_KEY>" `
  -Port 8787
```

## What gets created on server

- Backend directory: `/home/ubuntu/gethes-backend` (default)
- Python venv: `/home/ubuntu/gethes-backend/.venv`
- Environment file: `/etc/gethes/backend.env`
- Service: `gethes-oracle-backend.service`

## Verify

```bash
systemctl status gethes-oracle-backend --no-pager
curl http://127.0.0.1:8787/health
```
