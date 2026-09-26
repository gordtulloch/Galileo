# Galileo Installation Scripts

## Windows

| File | Purpose |
|---|---|
| [`Install-Galileo-Windows.bat`](../Install-Galileo-Windows.bat) (repo root) | The one file to download for a fresh install. Double-click it; it fetches `install.ps1` from GitHub and runs it. |
| `install.ps1` | Clones (or updates) the repo, ensures Git and Python 3.11+ are present (installing either if missing), creates `.venv`, installs dependencies, and creates a desktop shortcut. Safe to re-run any time. |
| `launch_galileo.bat` / `launch_galileo.ps1` | Installed as the desktop shortcut's target, which opens minimized. Checks for updates on every launch, then starts Galileo. `.bat` is the actual shortcut target (no PowerShell execution-policy prompt); `.ps1` is the same logic for a PowerShell prompt. Errors are appended to `%APPDATA%\Galileo\logs\launcher.log` rather than paused on-screen, since a minimized window's `pause` prompt would never be seen. |
| `upgrade.ps1` | Manual "update now" script - `git pull` plus a dependency refresh - for updating without starting the app, or after local changes blocked the automatic update. |

### How a fresh Windows install works

1. The user downloads and double-clicks `Install-Galileo-Windows.bat` from the repo root.
2. It downloads `install.ps1` and runs it via PowerShell (bypassing the execution-policy prompt for that one run only).
3. `install.ps1` resolves or installs Git (via `winget` if available, otherwise the latest Git for Windows release, looked up from GitHub) and Python 3.11 (via python.org), clones Galileo into `%USERPROFILE%\Galileo` (or wherever `-InstallDir` points), creates `.venv`, installs `requirements.txt`, and creates a `Galileo` desktop shortcut pointing at `launch_galileo.bat`.

Re-running `install.ps1` later (standalone, or from inside the checkout) is how to force a full refresh; ordinary use never needs it, because `launch_galileo.bat`/`.ps1` already update on every launch.

---

## macOS

| File | Purpose |
|---|---|
| [`Install-Galileo-MacOS.sh`](../Install-Galileo-MacOS.sh) (repo root) | The one file to download for a fresh install. Run it in Terminal; it fetches `install/install.sh` from GitHub and runs it. |
| `install.sh` | Clones (or updates) the repo, ensures Xcode CLT, Homebrew, and Python 3.11+ are present (installing each if missing), creates `.venv`, installs dependencies, and creates a desktop `.app` bundle. Safe to re-run any time. |
| `launch_galileo.sh` | Used as the desktop app bundle's target. Checks for updates on every launch, then starts Galileo. |
| `upgrade.sh` | Manual "update now" script - `git pull` plus a dependency refresh - for updating without starting the app, or after local changes blocked the automatic update. |

### How a fresh macOS install works

1. The user downloads `Install-Galileo-MacOS.sh` from the repo root.
2. They run `chmod +x Install-Galileo-MacOS.sh && ./Install-Galileo-MacOS.sh` in Terminal.
3. `install.sh` ensures Xcode Command Line Tools (provides `git`), optionally installs Homebrew, then installs Python 3.11 via Homebrew if needed. It clones Galileo into `~/Galileo` (or wherever `--install-dir` points), creates `.venv`, installs `requirements.txt`, and creates a `Galileo.app` bundle on the Desktop that wraps `launch_galileo.sh`.

Re-running `install.sh` later (standalone, or from inside the checkout) is how to force a full refresh; ordinary use never needs it because `launch_galileo.sh` already updates on every launch.

**Options accepted by `install.sh`:**

| Option | Default | Description |
|---|---|---|
| `--install-dir PATH` | `~/Galileo` | Where to clone the repo (standalone mode only). |
| `--repo-url URL` | GitHub upstream | Override the clone URL. |
| `--branch BRANCH` | `main` | Branch to track. |
| `--force` | off | Remove and recreate `.venv`. |
| `--quiet` | off | Accept all defaults without prompting. |

---

## Linux (Debian / Ubuntu)

| File | Purpose |
|---|---|
| [`Install-Galileo-Linux.sh`](../Install-Galileo-Linux.sh) (repo root) | The one file to download for a fresh install. Run it in a terminal; it fetches `install/install-linux.sh` from GitHub and runs it. |
| `install-linux.sh` | Clones (or updates) the repo, installs required `apt` packages (git, Python 3.11, Qt/PySide6 system libs), creates `.venv`, installs dependencies, and creates a desktop `.desktop` launcher and an application-menu entry. Safe to re-run any time. |
| `launch_galileo.sh` | Shared with macOS. Used as the desktop launcher's `Exec` target. Checks for updates on every launch, then starts Galileo. |
| `upgrade-linux.sh` | Manual "update now" script - `git pull` plus a dependency refresh - for updating without starting the app, or after local changes blocked the automatic update. |

### How a fresh Linux install works

1. The user downloads `Install-Galileo-Linux.sh` from the repo root.
2. They run `chmod +x Install-Galileo-Linux.sh && ./Install-Galileo-Linux.sh` in a terminal.
3. `install-linux.sh` installs missing `apt` packages (git, Python 3.11 via the [deadsnakes PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa) if the distro doesn't ship it, plus Qt6/PySide6 system libraries). It clones Galileo into `~/Galileo` (or wherever `--install-dir` points), creates `.venv`, installs `requirements.txt`, writes a `~/Desktop/Galileo.desktop` launcher, and copies it to `~/.local/share/applications` for the app menu.

Re-running `install-linux.sh` later (standalone, or from inside the checkout) is how to force a full refresh; ordinary use never needs it because `launch_galileo.sh` already updates on every launch.

#### Python 3.11 resolution strategy

The installer works through four strategies in order, stopping at the first that succeeds:

| # | When used | What it does |
|---|---|---|
| 1 | `apt-cache` shows `python3.11` | `apt-get install python3.11 python3.11-venv python3.11-dev` |
| 2 | Ubuntu family (Ubuntu, LUbuntu, **Stellarmate**, Mint, Pop!_OS …) and `python3.11` not in apt | Adds the [deadsnakes PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa) and installs via apt |
| 3 | Debian / **Raspberry Pi OS** Bullseye or older | Warns about the OS version, recommends upgrading to Bookworm, then falls through to pyenv |
| 4 | Any distro where apt can't supply 3.11 | Builds Python 3.11.9 from source via [pyenv](https://github.com/pyenv/pyenv) (~5 min on RPi 5, ~15 min on RPi 4) |

Distro detection reads `ID` and `ID_LIKE` from `/etc/os-release`. `ID_LIKE` is a space-separated list of parent distros, so Stellarmate (`ID=lubuntu ID_LIKE="ubuntu debian"`) correctly gets the deadsnakes PPA path rather than the Debian path.

**Options accepted by `install-linux.sh`:**

| Option | Default | Description |
|---|---|---|
| `--install-dir PATH` | `~/Galileo` | Where to clone the repo (standalone mode only). |
| `--repo-url URL` | GitHub upstream | Override the clone URL. |
| `--branch BRANCH` | `main` | Branch to track. |
| `--force` | off | Remove and recreate `.venv`. |
| `--quiet` | off | Accept all defaults without prompting. |

---

## The update system (all platforms)

Consistent with `docs/PSD.md` (`NFR-INSTALL-010`) and this project's general philosophy: Galileo updates itself with `git pull`/`git reset --hard` against a normal source checkout rather than shipping a rebuilt monolithic executable per release.

- **Automatic** - every time the desktop launcher runs (i.e. every time the desktop icon is used), it fetches `origin/main`, and if the checkout is behind *and* has no local changes, hard-resets to the latest commit before starting the app. Galileo's own database migrations (`galileo.library.database.init_db`) apply automatically the next time the app starts, so no separate migration step is needed after an update.
- **Manual** - `upgrade.ps1` / `upgrade.sh` does a plain `git pull` plus a dependency refresh, for updating without launching the app, or when the automatic path skipped itself because the install directory had local changes.
- Neither path ever discards local changes silently: both check `git status --porcelain` first and skip (with a message) rather than overwrite anything unexpected.

This mirrors the install system already proven on the author's [AstroFiler](https://github.com/gordtulloch/astrofiler-gui) project, adapted for Galileo's `python -m galileo.app` entry point.
