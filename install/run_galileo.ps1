# Starts Galileo: venv check, launch, and error logging. Split out of
# launch_galileo.ps1 so this half can change freely across releases - see
# the comment in launch_galileo.ps1 for why the update-check half can't.
# Runs minimized, so errors are appended to a log file rather than paused
# on-screen for a keypress no one will see.

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$LogDir = Join-Path $env:APPDATA "Galileo\logs"
$LogFile = Join-Path $LogDir "launcher.log"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

function Write-LauncherLog([string]$Message) {
    Add-Content -Path $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - run_galileo.ps1 - $Message"
}

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Error: Galileo's virtual environment was not found." -ForegroundColor Red
    Write-Host "Run install\install.ps1 first." -ForegroundColor Yellow
    Write-LauncherLog "ERROR: virtual environment not found - run install\install.ps1 first."
    exit 1
}

Write-Host "Starting Galileo..." -ForegroundColor Green
& $VenvPython -m galileo.app
if ($LASTEXITCODE -ne 0) {
    Write-Host
    Write-Host "Galileo exited with an error (code $LASTEXITCODE). See $LogFile." -ForegroundColor Red
    Write-LauncherLog "ERROR: Galileo exited with code $LASTEXITCODE."
    exit 1
}
