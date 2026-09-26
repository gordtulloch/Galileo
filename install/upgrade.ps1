# Galileo Upgrade Script for Windows (PowerShell)
# Manually pulls the latest code and refreshes dependencies. Runs in its own
# console window (green on black). The desktop shortcut/launch script already
# does this automatically on every launch (launch_galileo.ps1/.bat), so this
# script is for updating without starting the app, or after local changes
# blocked the automatic update.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

try {
    $Host.UI.RawUI.BackgroundColor = 'Black'
    $Host.UI.RawUI.ForegroundColor = 'Green'
    Clear-Host
} catch {
    # Ignore if host doesn't support color changes
}

function Show-DoneDialog([string]$message, [string]$title = 'Galileo') {
    try {
        Add-Type -AssemblyName PresentationFramework | Out-Null
        [System.Windows.MessageBox]::Show($message, $title, 'OK', 'Information') | Out-Null
    } catch {
        Write-Host $message
    }
}

function Show-ErrorDialog([string]$message, [string]$title = 'Galileo Upgrade Failed') {
    try {
        Add-Type -AssemblyName PresentationFramework | Out-Null
        [System.Windows.MessageBox]::Show($message, $title, 'OK', 'Error') | Out-Null
    } catch {
        Write-Host $message
    }
}

$exitCode = 0

try {

Write-Host "========================================" -ForegroundColor Green
Write-Host "Galileo Upgrade" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $RepoRoot

Write-Host "Working directory: $RepoRoot" -ForegroundColor Green
Write-Host ""

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git was not found on PATH. Install Git for Windows or update manually."
}

Write-Host "Running: git pull" -ForegroundColor Green
git pull
if ($LASTEXITCODE -ne 0) {
    throw "git pull failed - resolve any local changes/conflicts and try again."
}
Write-Host ""

$VenvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment not found. Run install\install.ps1 first."
}

Write-Host "Using Python: $VenvPython" -ForegroundColor Green
Write-Host ""

Write-Host "Upgrading pip..." -ForegroundColor Green
& $VenvPython -m pip install --upgrade pip
Write-Host ""

Write-Host "Installing requirements.txt..." -ForegroundColor Green
& $VenvPython -m pip install -r (Join-Path $RepoRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install one or more dependencies. See the output above."
}

Write-Host ""
Write-Host "Upgrade complete." -ForegroundColor Green

Show-DoneDialog "Galileo has been upgraded."
$exitCode = 0

} catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Show-ErrorDialog "Upgrade failed:`n`n$($_.Exception.Message)"
    $exitCode = 1
}

exit $exitCode
