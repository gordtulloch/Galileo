@echo off
REM Galileo launcher: checks for updates, then starts the app.
REM This is the desktop shortcut's actual target (a .bat needs no PowerShell
REM execution-policy handling to double-click). See launch_galileo.ps1 for
REM the same logic from a PowerShell prompt, and install\upgrade.ps1 for a
REM manual, on-demand update that doesn't also start the app.
setlocal EnableDelayedExpansion
cd /d "%~dp0\.."

if exist ".git" (
    where git >nul 2>&1
    if not errorlevel 1 (
        echo Checking for updates...
        git fetch origin main >nul 2>&1
        if not errorlevel 1 (
            set "BEHIND="
            for /f %%i in ('git rev-list HEAD..origin/main --count 2^>nul') do set BEHIND=%%i
            if defined BEHIND if not "!BEHIND!"=="0" (
                git status --porcelain >"%TEMP%\galileo-status.tmp" 2>nul
                for %%A in ("%TEMP%\galileo-status.tmp") do set STATUS_SIZE=%%~zA
                del "%TEMP%\galileo-status.tmp" >nul 2>&1
                if "!STATUS_SIZE!"=="0" (
                    echo Updating to the latest version...
                    git reset --hard origin/main >nul 2>&1
                    echo Updated.
                ) else (
                    echo Local changes found - skipping auto-update.
                )
            ) else (
                echo Already up to date.
            )
        ) else (
            echo Could not check for updates - continuing with the current version.
        )
        echo.
    )
)

set "LOG_DIR=%APPDATA%\Galileo\logs"
set "LOG_FILE=%LOG_DIR%\launcher.log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

if not exist ".venv\Scripts\python.exe" (
    echo Error: Galileo's virtual environment was not found.
    echo Run install\install.ps1 first.
    echo %date% %time% - launch_galileo.bat - ERROR - Virtual environment not found. Run install\install.ps1 first. >> "%LOG_FILE%"
    exit /b 1
)

echo Starting Galileo...
".venv\Scripts\python.exe" -m galileo.app
if errorlevel 1 (
    set "APP_EXIT_CODE=!errorlevel!"
    echo Galileo exited with an error (code !APP_EXIT_CODE!). See "%LOG_FILE%".
    echo %date% %time% - launch_galileo.bat - ERROR - Galileo exited with code !APP_EXIT_CODE!. >> "%LOG_FILE%"
    exit /b 1
)
