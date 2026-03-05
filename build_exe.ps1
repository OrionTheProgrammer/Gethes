param(
    [switch]$OneFile,
    [switch]$Clean,
    [switch]$NoZip,
    [switch]$Installer,
    [switch]$NoInstaller,
    [switch]$AutoInstallInno,
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
        [int]$MaxRetries = 6
    )

    $retries = [Math]::Max(1, $MaxRetries)
    for ($attempt = 1; $attempt -le $retries; $attempt++) {
        try {
            if (Test-Path $DestinationPath) {
                Remove-Item $DestinationPath -Force -ErrorAction SilentlyContinue
            }
            Compress-Archive -Path $Path -DestinationPath $DestinationPath -CompressionLevel Optimal
            return
        } catch {
            if ($attempt -ge $retries) {
                throw
            }
            $waitMs = [Math]::Min(3000, 400 * $attempt)
            Write-Host "ZIP temporalmente bloqueado ($attempt/$retries). Reintentando en $waitMs ms..."
            Start-Sleep -Milliseconds $waitMs
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
    "--add-data", "gethes/data;gethes/data",
    "--add-data", "gethes/assets;gethes/assets",
    "main.py"
)

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

if (-not $NoZip) {
    New-Item -ItemType Directory -Path "release" -Force | Out-Null

    if ($OneFile) {
        $zipPath = "release\\Gethes-v$version-win64-onefile.zip"
        if (Test-Path $zipPath) {
            Remove-Item $zipPath -Force
        }
        Compress-WithRetry -Path @("dist\\Gethes.exe") -DestinationPath $zipPath
        Write-Host "ZIP listo: $zipPath"
        $releaseArtifacts += (Resolve-Path $zipPath).Path
    } else {
        $zipPath = "release\\Gethes-v$version-win64-portable.zip"
        if (Test-Path $zipPath) {
            Remove-Item $zipPath -Force
        }
        Compress-WithRetry -Path @("dist\\Gethes\\*") -DestinationPath $zipPath
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
            & $isccPath "/DMyAppVersion=$version" "packaging\\GethesInstaller.iss"
            $setupPath = "release\\Gethes-Setup-v$version.exe"
            Sign-Target -FilePath $setupPath
            if (Test-Path $setupPath) {
                $releaseArtifacts += (Resolve-Path $setupPath).Path
            }
            Write-Host "Instalador listo en release\\"
        }
    }
}

Write-ReleaseChecksums -Version $version -ArtifactPaths $releaseArtifacts

Write-Host "Done. Check dist\\"
