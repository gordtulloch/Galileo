# Galileo launcher (PowerShell): checks for updates, then starts the app.
# Installed as the desktop shortcut's target by install.ps1 (via the .bat
# twin of this script). See install\upgrade.ps1 for a manual, on-demand
# update that doesn't also start the app.
#
# This file must only ever contain the update check below. If `git reset
# --hard` rewrites THIS file while it's still open for execution, the
# rewrite can leave it stuck "modified" relative to git (blocking a later
# manual `git pull`) without anyone editing it by hand. Anything that
# changes release to release - the venv check, the app launch, error
# logging - lives in run_galileo.ps1 instead, which is only ever opened
# *after* this block finishes, so changing it is always safe.

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

& (Join-Path $PSScriptRoot "run_galileo.ps1")
exit $LASTEXITCODE
