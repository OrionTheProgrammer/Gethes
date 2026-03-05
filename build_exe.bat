@echo off
setlocal

set ARG=

:parse
if "%~1"=="" goto run
if /I "%~1"=="onefile" set ARG=%ARG% -OneFile
if /I "%~1"=="clean" set ARG=%ARG% -Clean
if /I "%~1"=="installer" set ARG=%ARG% -Installer
if /I "%~1"=="autoinno" set ARG=%ARG% -AutoInstallInno
if /I "%~1"=="nozip" set ARG=%ARG% -NoZip
shift
goto parse

:run
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 %ARG%

endlocal
