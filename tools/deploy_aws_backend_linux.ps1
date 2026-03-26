param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,
    [Parameter(Mandatory = $true)]
    [string]$User,
    [Parameter(Mandatory = $true)]
    [string]$SshKeyPath,
    [string]$RemoteDir = "/home/ubuntu/gethes-backend",
    [string]$ServiceName = "gethes-cloud-backend",
    [string]$ApiKey = "",
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 443,
    [int]$OnlineWindowSeconds = 120
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [string[]]$Args = @()
    )
    & $Command @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $Command $($Args -join ' ')"
    }
}

function Write-LinuxText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Content
    )
    $normalized = $Content -replace "`r`n", "`n"
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $normalized, $encoding)
}

if (-not (Test-Path $SshKeyPath)) {
    throw "SSH key not found: $SshKeyPath"
}

$target = "$User@$HostName"
$sshBaseArgs = @("-i", $SshKeyPath, "-o", "StrictHostKeyChecking=accept-new")

Write-Host "[aws-deploy] Preparing remote directory $RemoteDir on $target"
Invoke-Checked -Command "ssh" -Args ($sshBaseArgs + @($target, "mkdir -p '$RemoteDir'"))

Write-Host "[aws-deploy] Uploading backend files"
Invoke-Checked -Command "scp" -Args ($sshBaseArgs + @("backend/aws_cloud_service.py", "$target`:$RemoteDir/aws_cloud_service.py"))

$envTemp = [IO.Path]::GetTempFileName()
$deployTemp = [IO.Path]::GetTempFileName()

try {
    $envLines = @(
        "GETHES_API_KEY=$ApiKey",
        "GETHES_BIND_HOST=$BindHost",
        "GETHES_PORT=$Port",
        "GETHES_ONLINE_WINDOW_SECONDS=$OnlineWindowSeconds",
        "GETHES_DB_PATH=$RemoteDir/gethes_telemetry.db"
    )
    Write-LinuxText -Path $envTemp -Content ($envLines -join "`n")

    $deployTemplate = @'
#!/usr/bin/env bash
set -euo pipefail

REMOTE_DIR="__REMOTE_DIR__"
SERVICE_NAME="__SERVICE_NAME__"

sudo apt-get update -y
sudo apt-get install -y python3 python3-venv

cd "$REMOTE_DIR"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

sudo mkdir -p /etc/gethes
sudo cp "$REMOTE_DIR/gethes-backend.env" /etc/gethes/aws-backend.env
sudo chmod 600 /etc/gethes/aws-backend.env

cat <<'UNIT' | sudo tee "/etc/systemd/system/__SERVICE_NAME__.service" >/dev/null
[Unit]
Description=Gethes AWS telemetry backend (SQLite)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/gethes/aws-backend.env
WorkingDirectory=__REMOTE_DIR__
ExecStart=__REMOTE_DIR__/.venv/bin/python __REMOTE_DIR__/aws_cloud_service.py --db-path ${GETHES_DB_PATH} --api-key ${GETHES_API_KEY} --host ${GETHES_BIND_HOST} --port ${GETHES_PORT} --online-window-seconds ${GETHES_ONLINE_WINDOW_SECONDS}
Restart=always
RestartSec=2
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl --no-pager --full status "$SERVICE_NAME"
'@

    $deployScript = $deployTemplate.Replace("__REMOTE_DIR__", $RemoteDir).Replace("__SERVICE_NAME__", $ServiceName)
    Write-LinuxText -Path $deployTemp -Content $deployScript

    Write-Host "[aws-deploy] Uploading env + deploy script"
    Invoke-Checked -Command "scp" -Args ($sshBaseArgs + @($envTemp, "$target`:$RemoteDir/gethes-backend.env"))
    Invoke-Checked -Command "scp" -Args ($sshBaseArgs + @($deployTemp, "$target`:$RemoteDir/deploy_aws_backend.sh"))

    Write-Host "[aws-deploy] Running remote install script"
    Invoke-Checked -Command "ssh" -Args ($sshBaseArgs + @($target, "chmod +x '$RemoteDir/deploy_aws_backend.sh' && '$RemoteDir/deploy_aws_backend.sh'"))
}
finally {
    Remove-Item -Path $envTemp -ErrorAction SilentlyContinue
    Remove-Item -Path $deployTemp -ErrorAction SilentlyContinue
}

Write-Host "[aws-deploy] Done."
