<#
.SYNOPSIS
    Launches Galileo from the repository root.
.EXAMPLE
    .\run.ps1
.EXAMPLE
    .\run.ps1 --some-arg
#>

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Prefer the project virtualenv if one exists, in either Windows or POSIX layout.
$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"
$VenvPythonPosix = Join-Path $ScriptDir ".venv/bin/python"

if (Test-Path $VenvPython) {
    $Python = $VenvPython
} elseif (Test-Path $VenvPythonPosix) {
    $Python = $VenvPythonPosix
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $Python = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $Python = "python3"
} else {
    Write-Error "No Python interpreter found (looked for .venv, python, python3)."
    exit 1
}

& $Python -m galileo.app @args
exit $LASTEXITCODE
