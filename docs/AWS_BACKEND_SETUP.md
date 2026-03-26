# AWS Backend Setup (EC2 + SQLite)

This is the AWS-native backend option for Gethes.

- Host: your Ubuntu EC2 instance
- DB: local SQLite file on the EC2 (no Oracle wallet required)
- Endpoints: same cloud contract (`/health`, `/v1/telemetry/heartbeat`, `/v1/telemetry/presence`)

## Deploy from Windows

```powershell
.\tools\deploy_aws_backend_linux.ps1 `
  -HostName "ec2-xx-xx-xx-xx.compute-1.amazonaws.com" `
  -User "ubuntu" `
  -SshKeyPath "C:\Users\orion\Downloads\getheskey.pem" `
  -Port 443
```

If you want API key auth:

```powershell
.\tools\deploy_aws_backend_linux.ps1 ... -ApiKey "YOUR_TOKEN"
```

## Verify on server

```bash
systemctl status gethes-cloud-backend --no-pager
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/v1/telemetry/presence
```

## Connect game client

Inside Gethes:

```text
cloud link http://<YOUR_PUBLIC_IP_OR_DOMAIN>:8787 <OPTIONAL_API_KEY>
```

If your Security Group only exposes `443`, keep backend on `-Port 443` and link:

```text
cloud link http://<YOUR_PUBLIC_IP_OR_DOMAIN>:443 <OPTIONAL_API_KEY>
```

## Data persisted

The SQLite DB (`gethes_telemetry.db`) stores:
- players + scores + preferences
- Syster training profile
- Syster feedback samples for incremental learning
