param(
    [string]$WalletZip = "C:\Users\orion\Downloads\Wallet_Gethes.zip",
    [string]$WalletDir = ".wallet_oracle_gethes",
    [string]$Dsn = "gethes_high",
    [string]$DbUser = "",
    [string]$DbPassword = "",
    [string]$ApiKey = "",
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8787,
    [int]$OnlineWindowSeconds = 120,
    [double]$TcpConnectTimeout = 6,
    [int]$RetryCount = 1,
    [int]$RetryDelay = 1
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($DbUser)) {
    if (-not [string]::IsNullOrWhiteSpace($env:GETHES_ORACLE_USER)) {
        $DbUser = $env:GETHES_ORACLE_USER
    } else {
        $DbUser = "ADMIN"
    }
}

if ([string]::IsNullOrWhiteSpace($DbPassword)) {
    if (-not [string]::IsNullOrWhiteSpace($env:GETHES_ORACLE_PASSWORD)) {
        $DbPassword = $env:GETHES_ORACLE_PASSWORD
    } else {
        $secure = Read-Host -Prompt "Oracle DB password for user '$DbUser'" -AsSecureString
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $DbPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        }
    }
}

$args = @(
    "-u", "backend/oracle_cloud_service.py",
    "--wallet-zip", $WalletZip,
    "--wallet-dir", $WalletDir,
    "--dsn", $Dsn,
    "--db-user", $DbUser,
    "--db-password", $DbPassword,
    "--host", $BindHost,
    "--port", "$Port",
    "--online-window-seconds", "$OnlineWindowSeconds",
    "--tcp-connect-timeout", "$TcpConnectTimeout",
    "--retry-count", "$RetryCount",
    "--retry-delay", "$RetryDelay"
)

if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
    $args += @("--api-key", $ApiKey)
}

Write-Host "[oracle] starting backend on http://$BindHost`:$Port using DSN '$Dsn'..." -ForegroundColor Cyan
python @args
