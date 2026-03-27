param(
    [string]$Model = "mistral",
    [string]$RuntimeSource = "",
    [string]$HostAddress = "127.0.0.1:11439",
    [switch]$SkipModelPull
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$packageDir = Join-Path $repoRoot "gethes"
$vendorRoot = Join-Path $packageDir "vendor\syster_core"
$runtimeTarget = Join-Path $vendorRoot "ollama"
$modelsTarget = Join-Path $vendorRoot "models"

if ([string]::IsNullOrWhiteSpace($RuntimeSource)) {
    $RuntimeSource = Join-Path $env:LOCALAPPDATA "Programs\Ollama"
}

if (-not (Test-Path $RuntimeSource)) {
    throw "Ollama runtime source not found: $RuntimeSource"
}

New-Item -ItemType Directory -Force -Path $runtimeTarget | Out-Null
New-Item -ItemType Directory -Force -Path $modelsTarget | Out-Null

Write-Host "Copying runtime from: $RuntimeSource"
Copy-Item -Path (Join-Path $RuntimeSource "*") -Destination $runtimeTarget -Recurse -Force

$runtimeExe = Join-Path $runtimeTarget "ollama.exe"
if (-not (Test-Path $runtimeExe)) {
    throw "Bundled runtime missing ollama.exe at: $runtimeExe"
}

if (-not $SkipModelPull) {
    Write-Host "Pulling model '$Model' into bundled models directory..."
    $env:OLLAMA_MODELS = $modelsTarget
    $env:OLLAMA_HOST = $HostAddress

    $serve = Start-Process -FilePath $runtimeExe -ArgumentList "serve" -PassThru -WindowStyle Hidden
    try {
        Start-Sleep -Seconds 3
        & $runtimeExe pull $Model
        if ($LASTEXITCODE -ne 0) {
            throw "Model pull failed with code $LASTEXITCODE"
        }
        & $runtimeExe list
    } finally {
        if ($serve -and -not $serve.HasExited) {
            Stop-Process -Id $serve.Id -Force -ErrorAction SilentlyContinue
        }
    }
} else {
    Write-Host "Skipping model pull. Runtime-only bundle prepared."
}

Write-Host "Syster Core bundle ready at: $vendorRoot"
Write-Host "Now build with: .\\build_exe.ps1 -BundleSysterCore"
