# Galileo Installation Scripts (Windows)

| File | Purpose |
|---|---|
| [`Install-Galileo.bat`](../Install-Galileo.bat) (repo root) | The one file to download for a fresh install. Double-click it; it fetches `install.ps1` from GitHub and runs it. |
| `install.ps1` | Clones (or updates) the repo, ensures Python 3.11+, creates `.venv`, installs dependencies, and creates a desktop shortcut. Safe to re-run any time. |
| `launch_galileo.bat` / `launch_galileo.ps1` | Installed as the desktop shortcut's target. Checks for updates on every launch, then starts Galileo. `.bat` is the actual shortcut target (no PowerShell execution-policy prompt); `.ps1` is the same logic for a PowerShell prompt. |
| `upgrade.ps1` | Manual "update now" script - `git pull` plus a dependency refresh - for updating without starting the app, or after local changes blocked the automatic update. |

## How a fresh install works

1. The user downloads and double-clicks `Install-Galileo.bat` from the repo root.
2. It downloads `install.ps1` and runs it via PowerShell (bypassing the execution-policy prompt for that one run only).
3. `install.ps1` clones Galileo into `%USERPROFILE%\Galileo` (or wherever `-InstallDir` points), resolves or installs Python 3.11, creates `.venv`, installs `requirements.txt`, and creates a `Galileo` desktop shortcut pointing at `launch_galileo.bat`.

Re-running `install.ps1` later (standalone, or from inside the checkout) is how to force a full refresh; ordinary use never needs it, because `launch_galileo.bat`/`.ps1` already update on every launch.

## The update system

Consistent with `docs/PSD.md` (`NFR-INSTALL-010`) and this project's general philosophy: Galileo updates itself with `git pull`/`git reset --hard` against a normal source checkout rather than shipping a rebuilt monolithic executable per release.

- **Automatic** - every time `launch_galileo.bat`/`.ps1` runs (i.e. every time the desktop icon is used), it fetches `origin/main`, and if the checkout is behind *and* has no local changes, hard-resets to the latest commit before starting the app. Galileo's own database migrations (`galileo.library.database.init_db`) apply automatically the next time the app starts, so no separate migration step is needed after an update.
- **Manual** - `upgrade.ps1` does a plain `git pull` plus a dependency refresh, for updating without launching the app, or when the automatic path skipped itself because the install directory had local changes.
- Neither path ever discards local changes silently: both check `git status --porcelain` first and skip (with a message) rather than overwrite anything unexpected.

This mirrors the install system already proven on the author's [AstroFiler](https://github.com/gordtulloch/astrofiler-gui) project, adapted for Galileo's `python -m galileo.app` entry point (no separate migration script, no per-launch console needed beyond error reporting).

macOS/Linux have no installer yet - use the existing [`run.sh`](../run.sh) from a manual `git clone` (see `TODO.md`).
