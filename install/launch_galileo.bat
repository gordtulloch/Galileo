@echo off
REM Galileo launcher: checks for updates, then starts the app.
REM This is the desktop shortcut's actual target (a .bat needs no PowerShell
REM execution-policy handling to double-click). See launch_galileo.ps1 for
REM the same logic from a PowerShell prompt, and install\upgrade.ps1 for a
REM manual, on-demand update that doesn't also start the app.
REM
REM This file must only ever contain the update check below. cmd.exe reads
REM a running .bat from disk by byte offset as it goes, so if `git reset
REM --hard` rewrites THIS file while it's mid-execution, further reads can
REM land on the wrong offset in the new content - which is how this file
REM previously ended up stuck "modified" relative to git (blocking a later
REM manual `git pull`) without anyone editing it by hand. Anything that
REM changes release to release - the venv check, the app launch, error
REM logging - lives in run_galileo.bat instead, which is only ever opened
REM *after* this block finishes, so changing it is always safe.
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

call "%~dp0run_galileo.bat"
exit /b %errorlevel%
