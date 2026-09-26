@echo off
REM Galileo Setup - the one file to download for a fresh install.
REM Double-click this file. It fetches install\install.ps1 from GitHub and
REM runs it, which clones Galileo, sets up Python/the virtual environment,
REM installs dependencies, and creates a desktop shortcut. Safe to re-run.
setlocal

title Galileo Setup

echo ========================================
echo  Galileo Setup
echo ========================================
echo.
echo This will download the Galileo installer and set up Galileo on this PC.
echo.

set "GALILEO_INSTALLER_URL=https://raw.githubusercontent.com/gordtulloch/Galileo/main/install/install.ps1"
set "GALILEO_TEMP_PS1=%TEMP%\galileo-install.ps1"

where powershell >nul 2>&1
if errorlevel 1 (
    echo Error: PowerShell is required and was not found on this system.
    pause
    exit /b 1
)

echo Downloading installer...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%GALILEO_INSTALLER_URL%' -OutFile '%GALILEO_TEMP_PS1%' -UseBasicParsing } catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }"
if errorlevel 1 (
    echo.
    echo Failed to download the Galileo installer. Check your internet connection
    echo or download the project manually from:
    echo   https://github.com/gordtulloch/Galileo
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%GALILEO_TEMP_PS1%" %*
set "EXIT_CODE=%ERRORLEVEL%"

del "%GALILEO_TEMP_PS1%" >nul 2>&1

echo.
pause
exit /b %EXIT_CODE%
