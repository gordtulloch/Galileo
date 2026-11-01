# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are pre-releases (`0.9.NNalpha`) tagged `v0.9.NNalpha`.

**Each release has its own archive file in [`docs/changelog/`](docs/changelog/)**, named after the version (e.g. [`0.9.03alpha.md`](docs/changelog/0.9.03alpha.md)); the older monthly files (`2026-09.md`, `2026-10.md`) hold entries from before versioned headings began. This file holds only `[Unreleased]` and the index below, so it stays short. Search the archives (`grep -rn <term> docs/changelog/`) rather than reading them end to end.

**At each release:** run `python scripts/archive_changelog.py <version>` (e.g. `0.9.04alpha`). It moves everything under `[Unreleased]` into `docs/changelog/<version>.md`, leaves `[Unreleased]` empty and adds a line to the index. Then bump the version in `galileo/__init__.py` and `pyproject.toml`, write `docs/release-notes/v<version>.md`, and tag.

## [Unreleased]

### Changed

- **The changelog is now versioned, with one archive file per release.** Until now everything accumulated under `[Unreleased]` in one 108 KB file. `CHANGELOG.md` now holds `[Unreleased]` and a Releases index; v0.9.03alpha's entries are in `docs/changelog/0.9.03alpha.md` and everything that shipped in 0.9.02alpha or before is in `docs/changelog/0.9.02alpha-and-earlier.md` (the entries present at the `v0.9.02alpha` tag; earlier releases could not be separated because the file had no version headings). New `scripts/archive_changelog.py <version>` does the archiving at each release, and the changelog section of `CLAUDE.md` describes the process. Replaces the rotate-at-40-KB-into-monthly-files rule. Documentation and tooling only.

## Releases

| Version | Date | Notes |
|---|---|---|
| 0.9.03alpha | 2026-10-31 | [Changelog](docs/changelog/0.9.03alpha.md), [GitHub release](https://github.com/gordtulloch/Galileo/releases/tag/v0.9.03alpha) |
| 0.9.02alpha and earlier (0.9.0alpha, 0.9.01alpha) | 2026-10-25 and before | [Changelog](docs/changelog/0.9.02alpha-and-earlier.md), [GitHub releases](https://github.com/gordtulloch/Galileo/releases) |
