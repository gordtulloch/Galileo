# AstroFiler Back Propagation

A running list of changes made to Galileo's vendored AstroFiler code (`galileo/library/`, `galileo/ui/library/`,
`galileo/commands/`) that should also be applied to the upstream AstroFiler project.

**Rule:** any change that touches Library code is added here in the same turn it is made (newest first).
Each entry says what changed, why, which Galileo files carry it, and anything Galileo-specific that must
be translated when applying it to AstroFiler (module paths, settings store, event bus, etc.).

Status values: `Pending` (not yet applied to AstroFiler), `Applied` (with the AstroFiler commit).

---

## 2026-11-10 — Multi-select delete on the Images tab — Status: Pending

**Change:** Library > Images lets you select several frames (Shift = range, Ctrl = toggle) and delete them
with one confirmation.
- `file_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)` (import `QAbstractItemView`).
- `show_file_context_menu`: when more than one row is selected and the clicked row is among them, the menu is
  just `Delete (N files)`; only child (file) rows with a filename, and not flagged `on_master`
  (`item.data(8, UserRole) == "on_master"`), are included. Nothing eligible -> no menu.
- New `_delete_files(filenames)`: honours `suppress_delete_warnings`, confirms once, then one
  `fitsFile.update(fitsFileSoftDelete=True).where(fitsFileName.in_(...))`, reloads, and warns if fewer rows
  were updated than requested.
- `_show_delete_confirmation_with_checkbox(filename, count=1)`: title/wording switch to "Delete Files" /
  "these N files" when `count > 1`.

**Galileo-specific to translate:** `load_library_config`/`save_library_config` and the `FitsFileModel` alias.
**Files:** `galileo/ui/library/images_widget.py`.

---

## 2026-11-10 — Seestar frames are no longer treated as precalibrated — Status: Pending

**Why:** Galileo also captures Seestar frames itself as raw BLOBs, which are not calibrated. Frames *downloaded*
from a Seestar (SMB/FTP) ARE calibrated, so the Seestar rule is kept for downloads only. Apply only if
AstroFiler ingests raw Seestar FITS by some other route; otherwise skip the removals below and just keep
AstroFiler's existing download behaviour.

**Change:** remove every `'seestar' in instrument` test from the precalibrated decision, leaving
`'itelescope' in telescope.lower()`:
- `fitsFile.isPrecalibrated()`-style check (`galileo/library/models/fits_file.py`).
- Ingest `fitsFileCalibrated` flag (`galileo/library/core/file_processing.py`).
- Sessions UI: `sessions_menu.py` (stack output dir), `sessions_stacking.py` (two places),
  `sessions_tree.py` (Resources cell no longer shows a Seestar source).

**Download exception (add to the above):** `registerFitsImage(root, file, moveFiles, precalibrated=False)` and
`submitFileToDB(..., precalibrated=False)` take the flag (also through the `fitsProcessing` facade in
`galileo/library/core/__init__.py`); `submitFileToDB` sets `fitsFileCalibrated=1` for iTelescope **or**
`precalibrated`. The download paths pass `precalibrated=(telescope_type == 'SeeStar')`:
`download_files()` in `galileo/commands/download.py` and `_register_download()` in
`galileo/ui/library/download_dialog.py`. Session-level labels (`sessions_tree`, `sessions_menu`,
`sessions_stacking`) stay iTelescope-only; per-frame calibrated flags skip re-calibration.

Existing rows keep their old calibrated flag until the calibration state is reset or the files re-imported.

---

## 2026-11-10 — Register masters from the Masters folder only — Status: Pending

**Change:** `registerMasters(source_folder=...)` is now given `os.path.join(repoFolder, "Masters")` instead of
the whole repository, so ingest does not open every image's header looking for masters. Two call sites:
`fitsProcessing` ingest (`galileo/library/core/__init__.py`, `folder` + "Masters") and the Images tab
register-masters step (`galileo/ui/library/images_widget.py`, `repoFolder` + "Masters"). Assumes masters live
in the repository's `Masters` folder (true of Galileo's repository layout; confirm for AstroFiler's).

---

## 2026-11-10 — Faster SFTP downloads from smart telescopes — Status: Pending

**Problem:** downloading images from a remote device over SFTP took far longer than the data warranted.

**Changes (three causes, all fixed):**

1. **One SSH connection per batch instead of one per file.** Opening an SSH connection (key exchange +
   login) is slow on a Raspberry Pi and was paid for every file downloaded or deleted.
   - `SftpMixin` (`galileo/library/services/telescope_sftp.py`) now keeps a per-host cache of open
     `SftpSession`s: class attributes `_sftp_sessions` (dict) and `_sftp_lock` (`threading.Lock`).
   - New methods: `_shared_sftp(host)` (returns the cached session, reopening it if `is_alive()` is false),
     `_drop_shared_sftp(host)`, `close_sftp_sessions()`.
   - `_download_file_sftp` and `_delete_file_sftp` use `_shared_sftp(host)`; on any non-cancel failure they
     call `_drop_shared_sftp(host)` so the next file reopens a fresh connection.
   - `atexit` hook `_close_all_at_exit()` closes anything left open. Listing (`_get_fits_files_sftp`) still
     uses its own `with` session — unchanged.
   - Callers end a batch with `close_sftp_sessions()`:
     `TelescopeDownloadWorker.run()` (`galileo/ui/library/download_dialog.py`, in a `finally:`) and
     `download_files()` (`galileo/commands/download.py`, before the final summary log/return).
2. **Wider SFTP window.** In `SftpSession.open()` (`galileo/library/adapters/sftp.py`) set
   `transport.default_window_size = _SFTP_WINDOW` (32 MiB; module constant) after `connect()` and *before*
   `client.open_sftp()`, so the prefetching reader keeps many 32 KB requests in flight. paramiko's default
   2 MB window stalls throughput on a LAN. (Must be set before `open_sftp()` — the channel takes the
   window size when it is created.)
3. **Skip agent/key probing when credentials are explicit.** When a password or `key_path` is configured,
   pass `allow_agent=False, look_for_keys=False` to `client.connect()` so paramiko does not try the SSH
   agent and every key in `~/.ssh` first (slow login).

   Also added `SftpSession.is_alive()` — true while the SSH transport is still active (used by the cache).

**Galileo-specific to translate:** `get_sftp_settings()` comes from `galileo.library.config`; AstroFiler
reads its own `.ini` equivalent. Tests in Galileo (`tests/test_lib.py`, `tests/test_commands.py`) needed
their fake sessions/managers extended with `get_transport`, `open_sftp` and `close_sftp_sessions`.

**Galileo files:** `galileo/library/adapters/sftp.py`, `galileo/library/services/telescope_sftp.py`,
`galileo/ui/library/download_dialog.py`, `galileo/commands/download.py`.
