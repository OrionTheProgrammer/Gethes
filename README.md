# Gethes v0.01

Juego interactivo tipo terminal, ejecutado completamente en `pygame-ce`.

## Incluye

- UI 100% Pygame con escala responsiva (`uiscale`) y modo pantalla completa (`F11`).
- Optimizacion por nivel de `graphics` (FPS objetivo y efectos ajustados).
- Intro animada al inicio con identidad de Gethes.
- Sistema de logros con notificaciones en esquina superior derecha + sonido.
- Minijuegos:
  - `snake`
  - `ahorcado1` / `hangman1`
  - `ahorcado2` / `hangman2`
  - `gato` / `tictactoe`
  - `codigo` / `codebreaker`
- Modo historia y perfiles por slots.
- Idiomas ES/EN/PT con deteccion automatica (`lang auto`).
- Syster local mejorado + modo hibrido opcional (`syster mode hybrid`) via endpoint remoto.
- Soporte de iconos SVG con `pyconify` + `pygame-ce`.

## Requisitos

- Python 3.10+
- Dependencias:
  - `pygame-ce>=2.5.7`
  - `pyconify>=0.2.1`

## Instalacion

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Ejecutar

```bash
python main.py
```

## Comandos utiles

- `help`
- `menu`
- `logros`
- `theme list`
- `theme <preset>`
- `theme <bg> <fg>`
- `uiscale <valor>`
- `options`
- `graphics <low|medium|high>`
- `update status`
- `update check`
- `update install`
- `update repo <owner/repo>`
- `update auto <on|off>`
- `syster mode <off|lite|lore|hybrid>`
- `syster endpoint <url|off>`
- `slots`
- `savegame`
- `exit`

Tambien puedes preconfigurar IA remota con variable de entorno:

```powershell
$env:GETHES_SYSTER_ENDPOINT=\"https://tu-endpoint\"
```

## Guardado

- Slots: `%APPDATA%\Gethes\saves\slot_1.json` (2 y 3 analogos)
- Config global: `%APPDATA%\Gethes\gethes_config.json`

## Build de .exe

### PowerShell (recomendado)

```powershell
.\build_exe.ps1
```

Por defecto construye `--onedir` y `--noupx` para reducir falsos positivos.
Ademas genera ZIP portable y, por defecto, intenta generar tambien instalador (`Setup`) para distribucion.

Para generar instalador (usuarios finales, experiencia mas simple):

```powershell
.\build_exe.ps1 -Installer
```

Si no tienes Inno Setup, el script puede intentar instalarlo automaticamente:

```powershell
.\build_exe.ps1 -Installer -AutoInstallInno
```

Si quieres solo version portable y sin instalador:

```powershell
.\build_exe.ps1 -NoInstaller
```

Salida esperada:
- `release\Gethes-v0.01-win64-portable.zip`
- `release\Gethes-Setup-v0.01.exe` (si tienes Inno Setup instalado)

Para generar `onefile`:

```powershell
.\build_exe.ps1 -OneFile
```

Para firmar (recomendado en distribucion):

```powershell
.\build_exe.ps1 -PfxPath "C:\ruta\certificado.pfx" -PfxPassword "tu_password"
```

Tambien puedes firmar por huella de certificado ya instalado (token/HSM o store local):

```powershell
.\build_exe.ps1 -CertThumbprint "TU_HUELLA_SHA1"
```

Si el certificado esta en el store de equipo (LocalMachine):

```powershell
.\build_exe.ps1 -CertThumbprint "TU_HUELLA_SHA1" -UseMachineStore
```

Si quieres firmar tambien el instalador:

```powershell
.\build_exe.ps1 -Installer -PfxPath "C:\ruta\certificado.pfx" -PfxPassword "tu_password"
```

Si `signtool` no existe, instala Windows SDK:

```powershell
winget install --id Microsoft.WindowsSDK.10.0.26100 -e --accept-source-agreements --accept-package-agreements
```

### BAT rapido

```bat
build_exe.bat
```

Tambien acepta parametros:

```bat
build_exe.bat clean installer
```

Auto instalacion de Inno Setup:

```bat
build_exe.bat clean installer autoinno
```

Solo portable (sin setup):

```bat
build_exe.bat clean noinstaller
```

## Error comun: "Failed to load Python DLL ... _internal\\python313.dll"

Ese error ocurre cuando se ejecuta el `.exe` sin su carpeta `_internal` (o un antivirus elimina DLLs).

Solucion recomendada:

1. Compartir el ZIP de `release\` (no solo el `.exe`).
2. Extraer todo el ZIP y ejecutar `Launch-Gethes.bat` o `Gethes.exe` sin moverlos de carpeta.
3. Si persiste, revisar cuarentena del antivirus y restaurar los archivos.

## Nota importante sobre Windows Defender / SmartScreen

No existe un cambio de codigo que garantice eliminar el aviso de "app peligrosa" en un binario nuevo sin firma.

Mitigaciones reales:

1. Distribuir en `onedir` (menos sospechoso que `onefile` en muchos casos).
2. Compilar sin UPX (`--noupx`).
3. Firmar digitalmente el `.exe` con certificado valido.
4. Mantener hash/version estables por release.
5. Si hay falso positivo, enviar muestra a Microsoft Defender para revision.

## Actualizacion automatica (GitHub Releases)

El actualizador integrado consulta GitHub Releases y descarga el instalador de la version mas reciente.

Requisitos de release:
1. Publicar tag de version (ejemplo: `v0.02`).
2. Adjuntar un asset instalador `.exe` (ejemplo: `Gethes-Setup-v0.02.exe`).

Configurar repositorio dentro del juego:

```text
update repo TU_USUARIO/TU_REPO
update auto on
```

Opcional por variable de entorno:

```powershell
$env:GETHES_UPDATE_REPO=\"TU_USUARIO/TU_REPO\"
```

Actualizar manualmente:

```text
update check
update install
```
