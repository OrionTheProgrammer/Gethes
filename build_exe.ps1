param(
    [switch]$OneFile,
    [switch]$Clean,
    [switch]$NoZip,
    [switch]$Installer,
    [switch]$NoInstaller,
    [switch]$AutoInstallInno,
    [switch]$BundleSysterCore,
    [switch]$BundleSysterModel,
    [switch]$RequireSysterCoreBundle,
    [switch]$SkipSysterBundle,
    [switch]$FastArtifacts,
    [string]$SysterModel = "mistral",
    [string]$SysterRuntimeSource = "",
    [string]$PfxPath = "",
    [string]$PfxPassword = "",
    [string]$CertThumbprint = "",
    [switch]$UseMachineStore,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

if (-not [string]::IsNullOrWhiteSpace($PfxPath) -and -not [string]::IsNullOrWhiteSpace($CertThumbprint)) {
    throw "Usa solo una via de firma: PFX o CertThumbprint, no ambas."
}

if (-not [string]::IsNullOrWhiteSpace($PfxPath) -and -not (Test-Path $PfxPath)) {
    throw "No se encontro el PFX: $PfxPath"
}

function Resolve-Iscc {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Path
    }

    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

function Resolve-AppVersion {
    $version = "0.04"
    if (Test-Path "gethes\\__init__.py") {
        $match = Select-String -Path "gethes\\__init__.py" -Pattern '__version__\s*=\s*"([^"]+)"' -AllMatches
        if ($match -and $match.Matches.Count -gt 0) {
            $version = $match.Matches[0].Groups[1].Value
        }
    }
    return $version
}

function Get-SysterCoreBundleState {
    $vendorRoot = Join-Path (Resolve-Path ".").Path "gethes\vendor\syster_core"
    $runtimeExe = Join-Path $vendorRoot "ollama\ollama.exe"
    $modelsRoot = Join-Path $vendorRoot "models"
    $manifestRoot = Join-Path $modelsRoot "manifests"
    $blobsRoot = Join-Path $modelsRoot "blobs"

    $hasRuntime = Test-Path $runtimeExe
    $hasModels = (Test-Path $manifestRoot) -and (Test-Path $blobsRoot)

    return [PSCustomObject]@{
        VendorRoot = $vendorRoot
        RuntimeExe = $runtimeExe
        ModelsRoot = $modelsRoot
        HasRuntime = $hasRuntime
        HasModels = $hasModels
        Ready = ($hasRuntime -and $hasModels)
    }
}

function Ensure-SysterCoreBundle {
    param(
        [switch]$IncludeModel,
        [string]$Model = "mistral",
        [string]$RuntimeSource = ""
    )

    $prepScript = Join-Path "packaging" "prepare_syster_core_bundle.ps1"
    if (-not (Test-Path $prepScript)) {
        throw "No se encontro script de bundle Syster Core: $prepScript"
    }

    $bundleState = Get-SysterCoreBundleState
    $runtimeReady = $bundleState.HasRuntime
    $modelReady = $bundleState.HasModels

    if ($runtimeReady -and ($modelReady -or -not $IncludeModel)) {
        Write-Host "Syster Core bundle ya disponible. Runtime=$runtimeReady Models=$modelReady"
        return
    }

    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $prepScript, "-Model", $Model)
    if (-not [string]::IsNullOrWhiteSpace($RuntimeSource)) {
        $args += @("-RuntimeSource", $RuntimeSource)
    }
    if (-not $IncludeModel) {
        $args += "-SkipModelPull"
    }

    Write-Host "Preparando bundle Syster Core..."
    & powershell.exe @args
    if ($LASTEXITCODE -ne 0) {
        throw "Fallo la preparacion del bundle Syster Core (exit code $LASTEXITCODE)."
    }

    $verify = Get-SysterCoreBundleState
    if (-not $verify.HasRuntime) {
        throw "Bundle Syster Core incompleto: falta runtime ($($verify.RuntimeExe))."
    }
    if ($IncludeModel -and -not $verify.HasModels) {
        throw "Bundle Syster Core incompleto: faltan modelos en $($verify.ModelsRoot)."
    }
}

function Ensure-AppIconFile {
    $pngPath = "gethes\\assets\\icons\\getheslogo.png"
    $icoPath = "packaging\\getheslogo.ico"
    if (-not (Test-Path $pngPath)) {
        return ""
    }

    $rebuild = $true
    if (Test-Path $icoPath) {
        $pngTime = (Get-Item $pngPath).LastWriteTimeUtc
        $icoTime = (Get-Item $icoPath).LastWriteTimeUtc
        $rebuild = $icoTime -lt $pngTime
    }

    if ($rebuild) {
        Write-Host "Generando icono ICO desde $pngPath ..."
        $pythonScript = @"
from pathlib import Path
from PIL import Image

src = Path(r"$pngPath")
dst = Path(r"$icoPath")
dst.parent.mkdir(parents=True, exist_ok=True)
img = Image.open(src).convert("RGBA")
img.save(dst, format="ICO", sizes=[(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)])
"@
        try {
            $pythonScript | python -
            if ($LASTEXITCODE -ne 0) {
                Write-Host "No se pudo convertir icono PNG a ICO. Se continuara sin icono de ejecutable."
                return ""
            }
        } catch {
            Write-Host "No se pudo convertir icono PNG a ICO. Se continuara sin icono de ejecutable."
            return ""
        }
    }

    if (Test-Path $icoPath) {
        return $icoPath
    }
    return ""
}

function Resolve-SignTool {
    $cmd = Get-Command signtool -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Path
    }

    $candidatePatterns = @(
        "$env:ProgramFiles(x86)\Windows Kits\10\bin\*\x64\signtool.exe",
        "$env:ProgramFiles\Windows Kits\10\bin\*\x64\signtool.exe"
    )
    foreach ($pattern in $candidatePatterns) {
        $found = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($found) {
            return $found.FullName
        }
    }
    return $null
}

function Has-SigningInput {
    return ([string]::IsNullOrWhiteSpace($PfxPath) -eq $false) -or ([string]::IsNullOrWhiteSpace($CertThumbprint) -eq $false)
}

function Sign-Target {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath
    )

    if (-not (Has-SigningInput)) {
        return
    }

    if (-not (Test-Path $FilePath)) {
        Write-Host "No se encontro archivo para firmar: $FilePath"
        return
    }

    $signtoolPath = Resolve-SignTool
    if (-not $signtoolPath) {
        throw "signtool no encontrado. Instala Windows SDK para poder firmar."
    }

    Write-Host "Signing $FilePath ..."
    if (-not [string]::IsNullOrWhiteSpace($PfxPath)) {
        if ($PfxPassword) {
            & $signtoolPath sign /fd SHA256 /tr $TimestampUrl /td SHA256 /f $PfxPath /p $PfxPassword $FilePath
        } else {
            & $signtoolPath sign /fd SHA256 /tr $TimestampUrl /td SHA256 /f $PfxPath $FilePath
        }
    } else {
        $thumb = $CertThumbprint.Trim().Replace(" ", "")
        if ($UseMachineStore) {
            & $signtoolPath sign /fd SHA256 /tr $TimestampUrl /td SHA256 /sha1 $thumb /sm $FilePath
        } else {
            & $signtoolPath sign /fd SHA256 /tr $TimestampUrl /td SHA256 /sha1 $thumb $FilePath
        }
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Fallo la firma digital para $FilePath"
    }

    $sig = Get-AuthenticodeSignature -FilePath $FilePath
    Write-Host "Firma aplicada: $($sig.Status) | Subject: $($sig.SignerCertificate.Subject)"
}

function Write-ReleaseChecksums {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Version,
        [Parameter(Mandatory = $true)]
        [string[]]$ArtifactPaths
    )

    $resolved = @()
    foreach ($item in $ArtifactPaths) {
        if ([string]::IsNullOrWhiteSpace($item)) {
            continue
        }
        if (-not (Test-Path $item)) {
            continue
        }
        $resolved += (Resolve-Path $item).Path
    }

    if ($resolved.Count -eq 0) {
        Write-Host "Checksum omitido: no hay artefactos de release para registrar."
        return
    }

    $releaseDir = "release"
    New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

    $lines = @()
    foreach ($artifact in ($resolved | Sort-Object -Unique)) {
        $hash = (Get-FileHash -Path $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
        $name = Split-Path $artifact -Leaf
        $line = "$hash  $name"
        $lines += $line
        Set-Content -Path ($artifact + ".sha256") -Value $line -Encoding ASCII
    }

    $versioned = Join-Path $releaseDir "SHA256SUMS-v$Version.txt"
    $latest = Join-Path $releaseDir "SHA256SUMS.txt"
    Set-Content -Path $versioned -Value $lines -Encoding ASCII
    Set-Content -Path $latest -Value $lines -Encoding ASCII
    Write-Host "Checksums listos: $versioned y $latest"
}

function Compress-WithRetry {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Path,
        [Parameter(Mandatory = $true)]
        [string]$DestinationPath,
        [ValidateSet("Optimal", "Fastest", "NoCompression")]
        [string]$CompressionLevel = "Optimal",
        [int]$MaxRetries = 6
    )

    function Remove-FileWithRetry {
        param(
            [Parameter(Mandatory = $true)]
            [string]$FilePath,
            [int]$Retries = 8
        )
        if (-not (Test-Path $FilePath)) {
            return
        }

        for ($i = 1; $i -le [Math]::Max(1, $Retries); $i++) {
            try {
                Remove-Item -LiteralPath $FilePath -Force -ErrorAction Stop
                if (-not (Test-Path $FilePath)) {
                    return
                }
            } catch {
                if ($i -ge $Retries) {
                    throw
                }
                Start-Sleep -Milliseconds ([Math]::Min(2500, 250 * $i))
            }
        }
    }

    function New-StagingCopy {
        param(
            [Parameter(Mandatory = $true)]
            [string[]]$InputPaths
        )

        $stageDir = Join-Path $env:TEMP ("gethes_zip_stage_" + [Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $stageDir -Force | Out-Null

        foreach ($entry in $InputPaths) {
            if ($entry.IndexOfAny(@('*', '?', '[')) -ge 0) {
                $items = Get-ChildItem -Path $entry -Force -ErrorAction Stop
            } else {
                $item = Get-Item -LiteralPath $entry -Force -ErrorAction Stop
                $items = @($item)
            }

            foreach ($item in $items) {
                $destination = Join-Path $stageDir $item.Name
                if ($item.PSIsContainer) {
                    Copy-Item -LiteralPath $item.FullName -Destination $destination -Recurse -Force -ErrorAction Stop
                } else {
                    Copy-Item -LiteralPath $item.FullName -Destination $destination -Force -ErrorAction Stop
                }
            }
        }

        return $stageDir
    }

    function Invoke-PythonZip {
        param(
            [Parameter(Mandatory = $true)]
            [string]$SourceDir,
            [Parameter(Mandatory = $true)]
            [string]$ZipPath,
            [Parameter(Mandatory = $true)]
            [ValidateSet("Optimal", "Fastest", "NoCompression")]
            [string]$Level
        )

        $pyCompression = "zipfile.ZIP_DEFLATED"
        $pyCompressLevel = "6"
        if ($Level -eq "Fastest") {
            $pyCompressLevel = "1"
        }
        if ($Level -eq "NoCompression") {
            $pyCompression = "zipfile.ZIP_STORED"
            $pyCompressLevel = "None"
        }

        $pythonZipScript = @"
from pathlib import Path
import zipfile

src = Path(r'''$SourceDir''')
dst = Path(r'''$ZipPath''')

compress_level = $pyCompressLevel
kwargs = {"compression": $pyCompression}
if compress_level is not None:
    kwargs["compresslevel"] = compress_level

with zipfile.ZipFile(dst, "w", **kwargs) as zf:
    for item in src.rglob("*"):
        if item.is_file():
            zf.write(item, item.relative_to(src))
"@
        $pythonZipScript | python -
        if ($LASTEXITCODE -ne 0) {
            throw "Python ZIP fallback failed."
        }
    }

    $retries = [Math]::Max(1, $MaxRetries)
    for ($attempt = 1; $attempt -le $retries; $attempt++) {
        $stagePath = ""
        try {
            Remove-FileWithRetry -FilePath $DestinationPath -Retries 10
            $stagePath = New-StagingCopy -InputPaths $Path
            $stagePattern = Join-Path $stagePath "*"
            try {
                if ($CompressionLevel -eq "NoCompression") {
                    Invoke-PythonZip -SourceDir $stagePath -ZipPath $DestinationPath -Level $CompressionLevel
                } else {
                    Compress-Archive -Path $stagePattern -DestinationPath $DestinationPath -CompressionLevel $CompressionLevel -ErrorAction Stop
                }
            } catch {
                Write-Host "Compress-Archive failed. Falling back to Python zip writer..."
                Invoke-PythonZip -SourceDir $stagePath -ZipPath $DestinationPath -Level $CompressionLevel
            }
            return
        } catch {
            if ($attempt -ge $retries) {
                throw
            }
            $waitMs = [Math]::Min(3000, 400 * $attempt)
            Write-Host "ZIP temporalmente bloqueado ($attempt/$retries). Reintentando en $waitMs ms..."
            Start-Sleep -Milliseconds $waitMs
        } finally {
            if (-not [string]::IsNullOrWhiteSpace($stagePath) -and (Test-Path $stagePath)) {
                Remove-Item -LiteralPath $stagePath -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

$mode = "--onedir"
if ($OneFile) {
    $mode = "--onefile"
}

if (-not $OneFile -and -not $NoInstaller) {
    $Installer = $true
}

$bundleFlagsPassed = (
    $PSBoundParameters.ContainsKey("BundleSysterCore") -or
    $PSBoundParameters.ContainsKey("BundleSysterModel") -or
    $PSBoundParameters.ContainsKey("RequireSysterCoreBundle")
)
if (-not $SkipSysterBundle -and -not $bundleFlagsPassed) {
    $BundleSysterCore = $true
    $BundleSysterModel = $true
    $RequireSysterCoreBundle = $true
    Write-Host "Default build profile: bundling Syster Core runtime + mistral model."
}

$includeModelBundle = $BundleSysterModel
if ($includeModelBundle -and -not $BundleSysterCore) {
    $BundleSysterCore = $true
}
if (-not $PSBoundParameters.ContainsKey("FastArtifacts") -and $includeModelBundle) {
    $FastArtifacts = $true
    Write-Host "Fast artifact mode enabled (bundled model detected)."
}

$bundleState = Get-SysterCoreBundleState
if ($BundleSysterCore) {
    $bundleStart = [System.Diagnostics.Stopwatch]::StartNew()
    Ensure-SysterCoreBundle -IncludeModel:$includeModelBundle -Model $SysterModel -RuntimeSource $SysterRuntimeSource
    $bundleStart.Stop()
    Write-Host ("Syster bundle step completed in {0:N1} min." -f ($bundleStart.Elapsed.TotalMinutes))
    $bundleState = Get-SysterCoreBundleState
}

if ($RequireSysterCoreBundle -and -not $bundleState.HasRuntime) {
    throw "Falta runtime de Syster Core en gethes\\vendor\\syster_core\\ollama."
}
if ($RequireSysterCoreBundle -and $includeModelBundle -and -not $bundleState.HasModels) {
    throw "Faltan modelos de Syster Core en gethes\\vendor\\syster_core\\models."
}

if ($bundleState.HasRuntime) {
    Write-Host "Syster Core runtime incluido en build."
} else {
    Write-Host "Syster Core runtime NO incluido. Los jugadores veran runtime_downloading en primer uso."
}
if ($bundleState.HasModels) {
    Write-Host "Syster Core models incluidos en build."
} else {
    Write-Host "Syster Core models NO incluidos. El modelo se descargara en segundo plano."
}
if ($bundleState.HasRuntime -and $OneFile) {
    Write-Host "Aviso: --onefile con runtime Syster Core puede generar ejecutable muy grande."
}

$iconFile = Ensure-AppIconFile

$args = @(
    "-y",
    $mode,
    "--noconsole",
    "--noupx",
    "--name", "Gethes",
    "--version-file", "packaging/version_info.txt",
    "--hidden-import", "freesound",
    "--hidden-import", "watchdog.events",
    "--hidden-import", "watchdog.observers",
    "--hidden-import", "pygame_menu",
    "--hidden-import", "pymunk",
    "--hidden-import", "pytweening",
    "--hidden-import", "rapidfuzz",
    "--hidden-import", "httpx",
    "--hidden-import", "tenacity",
    "--hidden-import", "platformdirs",
    "--hidden-import", "gethes.application",
    "--hidden-import", "gethes.application.command_router",
    "--hidden-import", "gethes.application.domain_supervisor",
    "--hidden-import", "gethes.domain",
    "--hidden-import", "gethes.domain.resilience",
    "--collect-submodules", "gethes.application",
    "--collect-submodules", "gethes.domain",
    "--add-data", "gethes/data;gethes/data",
    "--add-data", "gethes/assets;gethes/assets",
    "--add-data", "gethes/vendor;gethes/vendor",
    "main.py"
)

if (-not [string]::IsNullOrWhiteSpace($iconFile)) {
    $args += @("--icon", $iconFile)
}

if ($Clean) {
    $args = @("--clean") + $args
}

Write-Host "Building Gethes with PyInstaller..."
python -m PyInstaller @args

$exePath = "dist\\Gethes\\Gethes.exe"
if ($OneFile) {
    $exePath = "dist\\Gethes.exe"
}
Sign-Target -FilePath $exePath

$version = Resolve-AppVersion
$releaseArtifacts = @()

if (-not $OneFile) {
    $notesPath = "dist\\Gethes\\LEEME-EJECUTAR.txt"
    $pythonDll = "python313.dll"
    try {
        $detectedDll = python -c "import sys; print(f'python{sys.version_info.major}{sys.version_info.minor}.dll')"
        if ($LASTEXITCODE -eq 0 -and $detectedDll) {
            $pythonDll = $detectedDll.Trim()
        }
    } catch {
    }

    $launcherPath = "dist\\Gethes\\Launch-Gethes.bat"
    @"
@echo off
setlocal
set APPDIR=%~dp0
if not exist "%APPDIR%_internal\$pythonDll" (
  echo ERROR: faltan archivos internos para ejecutar Gethes.
  echo No ejecutes solo el .exe: usa la carpeta completa.
  echo Si vino en ZIP, extraelo completo antes de ejecutar.
  pause
  exit /b 1
)
start "" "%APPDIR%Gethes.exe"
"@ | Set-Content -Path $launcherPath -Encoding ASCII

    @"
Gethes v$version

IMPORTANTE:
- Ejecuta SOLO este archivo: Gethes.exe
- NO muevas Gethes.exe fuera de esta carpeta.
- La carpeta _internal debe permanecer junto al .exe.
- Recomendado: iniciar con Launch-Gethes.bat (verifica estructura automaticamente).

Si aparece error de python313.dll:
1) Asegura que _internal exista junto al .exe.
2) Verifica que tu antivirus no haya puesto en cuarentena archivos de _internal.
3) Extrae todo el ZIP completo, no solo el .exe.
"@ | Set-Content -Path $notesPath -Encoding UTF8
}

$zipCompressionLevel = if ($FastArtifacts) { "NoCompression" } else { "Optimal" }
if ($FastArtifacts) {
    Write-Host "Fast artifact mode: ZIP compression disabled to reduce build time."
}

if (-not $NoZip) {
    New-Item -ItemType Directory -Path "release" -Force | Out-Null

    if ($OneFile) {
        $zipPath = "release\\Gethes-v$version-win64-onefile.zip"
        if (Test-Path $zipPath) {
            Remove-Item $zipPath -Force
        }
        Compress-WithRetry -Path @("dist\\Gethes.exe") -DestinationPath $zipPath -CompressionLevel $zipCompressionLevel
        Write-Host "ZIP listo: $zipPath"
        $releaseArtifacts += (Resolve-Path $zipPath).Path
    } else {
        $zipPath = "release\\Gethes-v$version-win64-portable.zip"
        if (Test-Path $zipPath) {
            Remove-Item $zipPath -Force
        }
        Compress-WithRetry -Path @("dist\\Gethes\\*") -DestinationPath $zipPath -CompressionLevel $zipCompressionLevel
        Write-Host "ZIP listo: $zipPath"
        $releaseArtifacts += (Resolve-Path $zipPath).Path
    }
}

if ($Installer) {
    if ($OneFile) {
        Write-Host "Installer omitido: solo soportado en modo onedir."
    } else {
        $version = Resolve-AppVersion

        $isccPath = Resolve-Iscc
        if (-not $isccPath -and $AutoInstallInno) {
            $winget = Get-Command winget -ErrorAction SilentlyContinue
            if ($winget) {
                Write-Host "Inno Setup no encontrado. Intentando instalar via winget..."
                & $winget.Path install --id JRSoftware.InnoSetup -e --silent --accept-source-agreements --accept-package-agreements
                $isccPath = Resolve-Iscc
            } else {
                Write-Host "No se encontro winget para instalar Inno Setup automaticamente."
            }
        }

        if (-not $isccPath) {
            Write-Host "Inno Setup no encontrado. Instala Inno Setup 6 para generar instalador:"
            Write-Host "https://jrsoftware.org/isdl.php"
        } else {
            Write-Host "Compilando instalador Inno Setup..."
            $isccArgs = @("/DMyAppVersion=$version")
            if ($FastArtifacts) {
                $isccArgs += "/DFastCompression=1"
                Write-Host "Fast artifact mode: using faster Inno compression profile."
            }
            $isccArgs += "packaging\\GethesInstaller.iss"
            & $isccPath @isccArgs
            $setupPath = "release\\Gethes-Setup-v$version.exe"
            Sign-Target -FilePath $setupPath
            if (Test-Path $setupPath) {
                $releaseArtifacts += (Resolve-Path $setupPath).Path
            }
            Write-Host "Instalador listo en release\\"
        }
    }
}

if ($releaseArtifacts.Count -gt 0) {
    Write-ReleaseChecksums -Version $version -ArtifactPaths $releaseArtifacts
} else {
    Write-Host "Checksum omitido: no hay artefactos en release (build local sin empaquetado)."
}

Write-Host "Done. Check dist\\"
