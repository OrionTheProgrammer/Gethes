param(
    [switch]$RuntimeOnly,
    [string]$Model = "mistral",
    [string]$RuntimeSource = ""
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildScript = Join-Path $scriptRoot "build_exe.ps1"

if (-not (Test-Path $buildScript)) {
    throw "No se encontro build_exe.ps1 en: $buildScript"
}

$buildArgs = @{
    Installer = $true
    BundleSysterCore = $true
    RequireSysterCoreBundle = $true
    SysterModel = $Model
}

if (-not $RuntimeOnly) {
    $buildArgs["BundleSysterModel"] = $true
}

if (-not [string]::IsNullOrWhiteSpace($RuntimeSource)) {
    $buildArgs["SysterRuntimeSource"] = $RuntimeSource
}

Write-Host "Iniciando build offline de Gethes..."
if ($RuntimeOnly) {
    Write-Host "Modo: runtime incluido, modelo NO incluido."
} else {
    Write-Host "Modo: runtime y modelo incluidos."
}

& $buildScript @buildArgs
