param(
    [string]$Model = "mistral",
    [string]$RuntimeSource = "",
    [string]$HostAddress = "127.0.0.1:11439",
    [switch]$SkipModelPull,
    [switch]$ForceModelPull
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$packageDir = Join-Path $repoRoot "gethes"
$vendorRoot = Join-Path $packageDir "vendor\syster_core"
$runtimeTarget = Join-Path $vendorRoot "ollama"
$modelsTarget = Join-Path $vendorRoot "models"

if ([string]::IsNullOrWhiteSpace($RuntimeSource)) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama"),
        (Join-Path $env:ProgramFiles "Ollama"),
        (Join-Path ${env:ProgramFiles(x86)} "Ollama")
    )
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path $candidate)) {
            $RuntimeSource = $candidate
            break
        }
    }
}

if (-not (Test-Path $RuntimeSource)) {
    throw "Ollama runtime source not found. Install Ollama or pass -RuntimeSource <path>."
}

New-Item -ItemType Directory -Force -Path $runtimeTarget | Out-Null
New-Item -ItemType Directory -Force -Path $modelsTarget | Out-Null

Write-Host "Copying runtime from: $RuntimeSource"
Copy-Item -Path (Join-Path $RuntimeSource "*") -Destination $runtimeTarget -Recurse -Force

$runtimeExe = Join-Path $runtimeTarget "ollama.exe"
if (-not (Test-Path $runtimeExe)) {
    throw "Bundled runtime missing ollama.exe at: $runtimeExe"
}

function Test-ModelAlreadyBundled {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ModelName,
        [Parameter(Mandatory = $true)]
        [string]$ModelsRoot
    )

    $modelToken = $ModelName.Trim().ToLower()
    if ([string]::IsNullOrWhiteSpace($modelToken)) {
        return $false
    }

    $tag = "latest"
    $libraryName = $modelToken
    if ($modelToken.Contains(":")) {
        $parts = $modelToken.Split(":", 2)
        $libraryName = $parts[0]
        $tag = $parts[1]
    }

    if ($libraryName.Contains("/")) {
        $manifestPath = Join-Path $ModelsRoot ("manifests\registry.ollama.ai\" + $libraryName.Replace("/", "\\") + "\\" + $tag)
    } else {
        $manifestPath = Join-Path $ModelsRoot "manifests\registry.ollama.ai\library\$libraryName\$tag"
    }
    $blobsPath = Join-Path $ModelsRoot "blobs"

    if (-not (Test-Path $manifestPath) -or -not (Test-Path $blobsPath)) {
        return $false
    }

    $blobAny = Get-ChildItem -Path $blobsPath -File -ErrorAction SilentlyContinue | Select-Object -First 1
    return $null -ne $blobAny
}

if (-not $SkipModelPull) {
    if (-not $ForceModelPull -and (Test-ModelAlreadyBundled -ModelName $Model -ModelsRoot $modelsTarget)) {
        Write-Host "Model '$Model' already present in bundle. Skipping pull."
        Write-Host "Syster Core bundle ready at: $vendorRoot"
        Write-Host "Now build with: .\\build_exe.ps1 -BundleSysterCore -BundleSysterModel"
        exit 0
    }

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
        Write-Host "Model pull finished. Listing installed models:"
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
