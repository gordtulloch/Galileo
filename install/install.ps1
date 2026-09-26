# Galileo Installation Script for Windows (PowerShell)
# Clones (or updates) the Galileo repository, ensures Python 3.11+, creates a
# virtual environment, installs dependencies, and creates a desktop shortcut.
#
# Usage:
#   From inside an existing checkout:  .\install\install.ps1
#   Standalone (fetches the repo too): .\install.ps1 -InstallDir C:\Galileo
#
# This script is safe to re-run at any time - it refreshes dependencies and
# the shortcut rather than reinstalling from scratch. The desktop shortcut it
# creates (install\launch_galileo.bat) also checks for updates on every
# launch, so most users never need to re-run this script by hand; see
# install\launch_galileo.ps1 and install\upgrade.ps1 for the update system.

param(
    [string]$InstallDir,
    [string]$RepoUrl = "https://github.com/gordtulloch/Galileo.git",
    [string]$Branch = "main",
    [switch]$Force,
    [switch]$Quiet
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Galileo Installation Script for Windows" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host

function Update-SessionPath {
    # Winget/the downloaded installers update the registry but not this process's PATH.
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Install-Git {
    Write-Host "Git was not found." -ForegroundColor Yellow
    $installChoice = "Y"
    if (-not $Quiet) {
        $installChoice = Read-Host "Download and install Git for Windows now? [Y/n]"
    }
    if ($installChoice -match "^[Nn]") {
        Write-Host "Please install Git for Windows from https://git-scm.com/download/win and re-run this script." -ForegroundColor Yellow
        if (-not $Quiet) { Read-Host "Press Enter to exit" }
        exit 1
    }

    # Prefer winget when it's available - it stays current without us tracking a version number.
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Installing Git via winget..." -ForegroundColor Yellow
        & winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) {
            Update-SessionPath
            if (Get-Command git -ErrorAction SilentlyContinue) {
                Write-Host "Git installed." -ForegroundColor Green
                return
            }
        }
        Write-Host "winget install did not complete; falling back to a direct download." -ForegroundColor Yellow
    }

    Write-Host "Looking up the latest Git for Windows release..." -ForegroundColor Yellow
    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/git-for-windows/git/releases/latest" -UseBasicParsing
        $asset = $release.assets | Where-Object { $_.name -match "-64-bit\.exe$" } | Select-Object -First 1
        if (-not $asset) { throw "No 64-bit installer found in the latest release." }
    } catch {
        Write-Host "Error looking up the latest Git release: $_" -ForegroundColor Red
        Write-Host "Please install Git for Windows manually from https://git-scm.com/download/win" -ForegroundColor Yellow
        if (-not $Quiet) { Read-Host "Press Enter to exit" }
        exit 1
    }

    $installerPath = Join-Path $env:TEMP $asset.name
    Write-Host "Downloading $($asset.name)..." -ForegroundColor Yellow
    try {
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $installerPath -UseBasicParsing
    } catch {
        Write-Host "Error downloading Git: $_" -ForegroundColor Red
        Write-Host "Please install Git for Windows manually from https://git-scm.com/download/win" -ForegroundColor Yellow
        if (-not $Quiet) { Read-Host "Press Enter to exit" }
        exit 1
    }

    Write-Host "Installing Git for Windows (this can take a minute)..." -ForegroundColor Yellow
    # Silent, current-user install - Galileo only needs `git` itself on PATH, not the shell extras.
    $process = Start-Process -FilePath $installerPath -ArgumentList "/VERYSILENT /NORESTART /NOCANCEL /SP- /CURRENTUSER" -Wait -PassThru
    Remove-Item $installerPath -Force -ErrorAction SilentlyContinue

    if ($process.ExitCode -ne 0) {
        Write-Host "Git installation failed with exit code $($process.ExitCode)." -ForegroundColor Red
        if (-not $Quiet) { Read-Host "Press Enter to exit" }
        exit 1
    }

    Update-SessionPath
    Write-Host "Git installed." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Locate (or clone) the Galileo repository
# ---------------------------------------------------------------------------
# Running from inside an existing checkout (install\install.ps1): use it in
# place, the same as re-running the installer to refresh an install.
# Otherwise (this file was downloaded standalone) clone/update a checkout at
# -InstallDir.
$ParentDir = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { $null }
if ($ParentDir -and (Test-Path (Join-Path $ParentDir "pyproject.toml"))) {
    $RepoRoot = $ParentDir
} else {
    if (-not $InstallDir) { $InstallDir = Join-Path $env:USERPROFILE "Galileo" }

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Install-Git
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "Error: still could not find git after installation." -ForegroundColor Red
        Write-Host "Close this window, open a new PowerShell session (so PATH updates take effect) and re-run this script." -ForegroundColor Yellow
        if (-not $Quiet) { Read-Host "Press Enter to exit" }
        exit 1
    }

    if (Test-Path (Join-Path $InstallDir ".git")) {
        Write-Host "Existing Galileo checkout found at $InstallDir - updating..." -ForegroundColor Yellow
        Push-Location $InstallDir
        $dirty = git status --porcelain
        if ($dirty) {
            Write-Host "Warning: local changes found in $InstallDir - skipping git pull." -ForegroundColor Yellow
        } else {
            git fetch origin $Branch
            git checkout $Branch
            git pull --ff-only origin $Branch
        }
        Pop-Location
    } else {
        Write-Host "Cloning Galileo into $InstallDir..." -ForegroundColor Yellow
        git clone --branch $Branch $RepoUrl $InstallDir
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Error: git clone failed." -ForegroundColor Red
            if (-not $Quiet) { Read-Host "Press Enter to exit" }
            exit 1
        }
    }
    $RepoRoot = $InstallDir
}

Set-Location $RepoRoot
Write-Host "Installing into: $RepoRoot" -ForegroundColor Green
Write-Host

# ---------------------------------------------------------------------------
# Python 3.11+ detection / installation
# ---------------------------------------------------------------------------
function Resolve-Python {
    # Prefer the py launcher's exact 3.11 - the version this project develops/tests on.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { return @("py", "-3.11") }
    }
    foreach ($cmd in @("python", "python3")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            & $cmd -c "import sys; exit(0 if sys.version_info[:2] >= (3, 11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return @($cmd) }
        }
    }
    return $null
}

function Invoke-Py {
    param([string[]]$PyArgs)
    if ($script:PythonCmd.Length -gt 1) {
        & $script:PythonCmd[0] $script:PythonCmd[1] @PyArgs
    } else {
        & $script:PythonCmd[0] @PyArgs
    }
}

function Install-Python {
    Write-Host "Python 3.11+ was not found." -ForegroundColor Yellow
    $installChoice = "Y"
    if (-not $Quiet) {
        $installChoice = Read-Host "Download and install Python 3.11 now? [Y/n]"
    }
    if ($installChoice -match "^[Nn]") {
        Write-Host "Please install Python 3.11+ from https://www.python.org/downloads/ (check 'Add python.exe to PATH') and re-run this script." -ForegroundColor Yellow
        if (-not $Quiet) { Read-Host "Press Enter to exit" }
        exit 1
    }

    $pythonUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $installerPath = Join-Path $env:TEMP "python-3.11.9-amd64.exe"
    Write-Host "Downloading Python 3.11.9..." -ForegroundColor Yellow
    try {
        Invoke-WebRequest -Uri $pythonUrl -OutFile $installerPath -UseBasicParsing
    } catch {
        Write-Host "Error downloading Python: $_" -ForegroundColor Red
        Write-Host "Please install Python 3.11+ manually from https://www.python.org/downloads/" -ForegroundColor Yellow
        if (-not $Quiet) { Read-Host "Press Enter to exit" }
        exit 1
    }

    Write-Host "Installing Python 3.11.9 (this can take a minute)..." -ForegroundColor Yellow
    $process = Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait -PassThru
    Remove-Item $installerPath -Force -ErrorAction SilentlyContinue

    if ($process.ExitCode -ne 0) {
        Write-Host "Python installation failed with exit code $($process.ExitCode)." -ForegroundColor Red
        if (-not $Quiet) { Read-Host "Press Enter to exit" }
        exit 1
    }

    Update-SessionPath
    Write-Host "Python 3.11.9 installed." -ForegroundColor Green
}

Write-Host "Checking Python installation..." -ForegroundColor Yellow
$PythonCmd = Resolve-Python
if (-not $PythonCmd) {
    Install-Python
    $PythonCmd = Resolve-Python
}
if (-not $PythonCmd) {
    Write-Host "Error: still could not find Python 3.11+ after installation." -ForegroundColor Red
    Write-Host "Close this window, open a new PowerShell session (so PATH updates take effect) and re-run this script." -ForegroundColor Yellow
    if (-not $Quiet) { Read-Host "Press Enter to exit" }
    exit 1
}
Write-Host "Using $(Invoke-Py -PyArgs @('--version')) ($($PythonCmd -join ' '))" -ForegroundColor Green
Write-Host

# ---------------------------------------------------------------------------
# Virtual environment
# ---------------------------------------------------------------------------
$VenvDir = Join-Path $RepoRoot ".venv"
if ((Test-Path $VenvDir) -and $Force) {
    Write-Host "Removing existing virtual environment (-Force)..." -ForegroundColor Yellow
    Remove-Item $VenvDir -Recurse -Force
}

if (-not (Test-Path $VenvDir)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    Invoke-Py -PyArgs @("-m", "venv", $VenvDir)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: failed to create the virtual environment." -ForegroundColor Red
        if (-not $Quiet) { Read-Host "Press Enter to exit" }
        exit 1
    }
} else {
    Write-Host "Using existing virtual environment." -ForegroundColor Green
}
Write-Host

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
Write-Host "Upgrading pip..." -ForegroundColor Yellow
& $VenvPython -m pip install --upgrade pip

Write-Host "Installing dependencies from requirements.txt (this downloads several scientific packages, allow a few minutes)..." -ForegroundColor Yellow
& $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: failed to install one or more dependencies. See the output above." -ForegroundColor Red
    if (-not $Quiet) { Read-Host "Press Enter to exit" }
    exit 1
}
Write-Host "Dependencies installed." -ForegroundColor Green
Write-Host

# ---------------------------------------------------------------------------
# Desktop shortcut
# ---------------------------------------------------------------------------
$createShortcut = "Y"
if (-not $Quiet) {
    $createShortcut = Read-Host "Create a desktop shortcut? [Y/n]"
}
if ($createShortcut -notmatch "^[Nn]") {
    try {
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut((Join-Path $WshShell.SpecialFolders("Desktop") "Galileo.lnk"))
        $Shortcut.TargetPath = Join-Path $RepoRoot "install\launch_galileo.bat"
        $Shortcut.WorkingDirectory = $RepoRoot
        $Shortcut.IconLocation = Join-Path $RepoRoot "assets\images\galileo.ico"
        $Shortcut.Description = "Galileo - Astrophotography Imaging Suite"
        $Shortcut.WindowStyle = 7  # Minimized - hides the update-check console; the Galileo window itself is unaffected.
        $Shortcut.Save()
        Write-Host "Desktop shortcut created." -ForegroundColor Green
    } catch {
        Write-Host "Warning: could not create the desktop shortcut: $_" -ForegroundColor Yellow
    }
}

Write-Host
Write-Host "========================================" -ForegroundColor Green
Write-Host "Galileo installation complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host
Write-Host "Start Galileo from the desktop shortcut, or run:" -ForegroundColor Cyan
Write-Host "  $RepoRoot\install\launch_galileo.bat" -ForegroundColor White
Write-Host
Write-Host "That launcher checks for updates (git pull) every time it starts." -ForegroundColor Cyan
Write-Host "To update by hand instead, run: $RepoRoot\install\upgrade.ps1" -ForegroundColor Cyan
Write-Host

if (-not $Quiet) { Read-Host "Press Enter to exit" }
