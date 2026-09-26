# Galileo launcher (PowerShell): checks for updates, then starts the app.
# Installed as the desktop shortcut's target by install.ps1 (via the .bat
# twin of this script). See install\upgrade.ps1 for a manual, on-demand
# update that doesn't also start the app.

param(
    [switch]$NoWait
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if ((Test-Path ".git") -and (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Checking for updates..." -ForegroundColor Yellow
    try {
        git fetch origin main 2>$null | Out-Null
        $behind = git rev-list HEAD..origin/main --count 2>$null
        if ($behind -and [int]$behind -gt 0) {
            if (git status --porcelain) {
                Write-Host "Local changes found - skipping auto-update. Run install\upgrade.ps1 to update by hand." -ForegroundColor Yellow
            } else {
                Write-Host "Updating to the latest version ($behind commit(s) behind)..." -ForegroundColor Green
                git reset --hard origin/main | Out-Null
                Write-Host "Updated." -ForegroundColor Green
            }
        } else {
            Write-Host "Already up to date." -ForegroundColor Green
        }
    } catch {
        Write-Host "Could not check for updates (offline?). Continuing with the current version." -ForegroundColor Yellow
    }
    Write-Host
}

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Error: Galileo's virtual environment was not found." -ForegroundColor Red
    Write-Host "Run install\install.ps1 first." -ForegroundColor Yellow
    if (-not $NoWait) { Read-Host "Press Enter to exit" }
    exit 1
}

Write-Host "Starting Galileo..." -ForegroundColor Green
& $VenvPython -m galileo.app
if ($LASTEXITCODE -ne 0) {
    Write-Host
    Write-Host "Galileo exited with an error (code $LASTEXITCODE)." -ForegroundColor Red
    if (-not $NoWait) { Read-Host "Press Enter to exit" }
}
