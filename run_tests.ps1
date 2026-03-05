param(
    [switch]$Fast
)

$ErrorActionPreference = "Stop"

function Test-XdistAvailable {
    try {
        python -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('xdist') else 1)"
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Invoke-PytestCommand {
    param(
        [switch]$UseFallback,
        [switch]$UseFast
    )

    if ($UseFallback) {
        $fallback = Join-Path $env:LOCALAPPDATA "Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts\pytest.exe"
        if (-not (Test-Path $fallback)) {
            return $false
        }
        if ($UseFast) {
            & $fallback -n auto | Out-Host
        } else {
            & $fallback | Out-Host
        }
        return $true
    }

    if ($UseFast) {
        python -m pytest -n auto | Out-Host
    } else {
        python -m pytest | Out-Host
    }
    return $true
}

Write-Host "Running Gethes logic tests..."

$useFast = $false
if ($Fast) {
    if (Test-XdistAvailable) {
        $useFast = $true
        Write-Host "Fast mode enabled: pytest-xdist detected (`-n auto`)."
    } else {
        Write-Host "Fast mode requested but pytest-xdist is not installed. Running regular mode."
    }
}

try {
    if (Invoke-PytestCommand -UseFast:$useFast) {
        exit $LASTEXITCODE
    }
} catch {
}

try {
    if (Invoke-PytestCommand -UseFallback -UseFast:$useFast) {
        exit $LASTEXITCODE
    }
} catch {
}

Write-Error "pytest is not available. Install dev dependencies with: python -m pip install -r requirements-dev.txt"
