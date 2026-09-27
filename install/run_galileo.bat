@echo off
REM Starts Galileo: venv check, launch, and error logging. Split out of
REM launch_galileo.bat so this half can change freely across releases - see
REM the comment in launch_galileo.bat for why the update-check half can't.
setlocal EnableDelayedExpansion
cd /d "%~dp0\.."

set "LOG_DIR=%APPDATA%\Galileo\logs"
set "LOG_FILE=%LOG_DIR%\launcher.log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

if not exist ".venv\Scripts\python.exe" (
    echo Error: Galileo's virtual environment was not found.
    echo Run install\install.ps1 first.
    echo %date% %time% - run_galileo.bat - ERROR - Virtual environment not found. Run install\install.ps1 first. >> "%LOG_FILE%"
    exit /b 1
)

echo Starting Galileo...
".venv\Scripts\python.exe" -m galileo.app
if errorlevel 1 (
    set "APP_EXIT_CODE=!errorlevel!"
    echo Galileo exited with an error (code !APP_EXIT_CODE!). See "%LOG_FILE%".
    echo %date% %time% - run_galileo.bat - ERROR - Galileo exited with code !APP_EXIT_CODE!. >> "%LOG_FILE%"
    exit /b 1
)
