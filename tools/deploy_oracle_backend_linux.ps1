param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,
    [Parameter(Mandatory = $true)]
    [string]$User,
    [Parameter(Mandatory = $true)]
    [string]$SshKeyPath,
    [string]$RemoteDir = "/home/ubuntu/gethes-backend",
    [string]$ServiceName = "gethes-oracle-backend",
    [string]$LocalWalletZipPath = "",
    [string]$RemoteWalletZipPath = "/home/ubuntu/gethes-backend/Wallet_Gethes.zip",
    [string]$Dsn = "gethes_high",
    [string]$DbUser = "ADMIN",
    [string]$DbPassword = "",
    [string]$WalletPassword = "",
    [string]$ApiKey = "",
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8787
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

if ([string]::IsNullOrWhiteSpace($DbPassword)) {
    if (-not [string]::IsNullOrWhiteSpace($env:GETHES_ORACLE_PASSWORD)) {
        $DbPassword = $env:GETHES_ORACLE_PASSWORD
    } else {
        throw "Missing DbPassword (or set GETHES_ORACLE_PASSWORD)."
    }
}

if ([string]::IsNullOrWhiteSpace($WalletPassword)) {
    if (-not [string]::IsNullOrWhiteSpace($env:GETHES_WALLET_PASSWORD)) {
        $WalletPassword = $env:GETHES_WALLET_PASSWORD
    }
}

$target = "$User@$HostName"
$sshBaseArgs = @("-i", $SshKeyPath, "-o", "StrictHostKeyChecking=accept-new")

Write-Host "[deploy] Preparing remote directory $RemoteDir on $target"
Invoke-Checked -Command "ssh" -Args ($sshBaseArgs + @($target, "mkdir -p '$RemoteDir'"))

Write-Host "[deploy] Uploading backend sources"
Invoke-Checked -Command "scp" -Args ($sshBaseArgs + @("backend/oracle_cloud_service.py", "$target`:$RemoteDir/oracle_cloud_service.py"))
Invoke-Checked -Command "scp" -Args ($sshBaseArgs + @("backend/requirements.txt", "$target`:$RemoteDir/requirements.txt"))

if (-not [string]::IsNullOrWhiteSpace($LocalWalletZipPath)) {
    if (-not (Test-Path $LocalWalletZipPath)) {
        throw "Local wallet zip not found: $LocalWalletZipPath"
    }
    Write-Host "[deploy] Uploading wallet zip"
    Invoke-Checked -Command "scp" -Args ($sshBaseArgs + @($LocalWalletZipPath, "$target`:$RemoteWalletZipPath"))
}

$envTemp = [IO.Path]::GetTempFileName()
$deployTemp = [IO.Path]::GetTempFileName()

try {
    $envLines = @(
        "GETHES_ORACLE_DSN=$Dsn",
        "GETHES_ORACLE_USER=$DbUser",
        "GETHES_ORACLE_PASSWORD=$DbPassword",
        "GETHES_API_KEY=$ApiKey",
        "GETHES_BIND_HOST=$BindHost",
        "GETHES_PORT=$Port",
        "GETHES_WALLET_ZIP=$RemoteWalletZipPath"
    )
    if (-not [string]::IsNullOrWhiteSpace($WalletPassword)) {
        $envLines += "GETHES_WALLET_PASSWORD=$WalletPassword"
    }
    Write-LinuxText -Path $envTemp -Content ($envLines -join "`n")

    $walletFlag = ""
    if (-not [string]::IsNullOrWhiteSpace($WalletPassword)) {
        $walletFlag = "--wallet-password `${GETHES_WALLET_PASSWORD}"
    }

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
pip install -r requirements.txt

sudo mkdir -p /etc/gethes
sudo cp "$REMOTE_DIR/gethes-backend.env" /etc/gethes/backend.env
sudo chmod 600 /etc/gethes/backend.env

cat <<'UNIT' | sudo tee "/etc/systemd/system/__SERVICE_NAME__.service" >/dev/null
[Unit]
Description=Gethes Oracle telemetry backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/gethes/backend.env
WorkingDirectory=__REMOTE_DIR__
ExecStart=__REMOTE_DIR__/.venv/bin/python __REMOTE_DIR__/oracle_cloud_service.py --wallet-zip ${GETHES_WALLET_ZIP} --wallet-dir __REMOTE_DIR__/.wallet_oracle --dsn ${GETHES_ORACLE_DSN} --db-user ${GETHES_ORACLE_USER} --db-password ${GETHES_ORACLE_PASSWORD} __WALLET_PASSWORD_FLAG__ --api-key ${GETHES_API_KEY} --host ${GETHES_BIND_HOST} --port ${GETHES_PORT}
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

    $deployScript = $deployTemplate.Replace("__REMOTE_DIR__", $RemoteDir).Replace("__SERVICE_NAME__", $ServiceName).Replace("__WALLET_PASSWORD_FLAG__", $walletFlag)
    Write-LinuxText -Path $deployTemp -Content $deployScript

    Write-Host "[deploy] Uploading env and deploy scripts"
    Invoke-Checked -Command "scp" -Args ($sshBaseArgs + @($envTemp, "$target`:$RemoteDir/gethes-backend.env"))
    Invoke-Checked -Command "scp" -Args ($sshBaseArgs + @($deployTemp, "$target`:$RemoteDir/deploy_backend.sh"))

    Write-Host "[deploy] Running remote install script"
    Invoke-Checked -Command "ssh" -Args ($sshBaseArgs + @($target, "chmod +x '$RemoteDir/deploy_backend.sh' && '$RemoteDir/deploy_backend.sh'"))
}
finally {
    Remove-Item -Path $envTemp -ErrorAction SilentlyContinue
    Remove-Item -Path $deployTemp -ErrorAction SilentlyContinue
}

Write-Host "[deploy] Done."
