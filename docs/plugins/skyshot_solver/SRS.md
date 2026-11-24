# Skyshot Solver Plugin — SRS (Software Requirements Specification)

| | |
|---|---|
| **Project** | Galileo — Skyshot Solver Plugin |
| **Document** | SRS (Software Requirements Specification), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-11-19 |
| **Upstream document** | [PSD](PSD.md) |
| **Downstream documents** | SDD ([SDD.md](SDD.md)), RTM ([RTM.md](RTM.md)) |
| **Parent project** | [Galileo Core SRS](../../SRS.md) |

---

## 1. Conventions

`<DOMAIN>-<###>` in increments of 10. Priority MVP / P2 / P3 as in [core SRS §1.4](../../SRS.md#14-priority-convention). This SRS decomposes the `SKY` domain of [the PSD](PSD.md); the core capabilities it consumes are cited by ID in PSD §5.

## 2. Requirements — `SKY` Skyshot Solver

| ID | Requirement | Priority |
|---|---|---|
| SKY-010 | The plugin shall register a solver backend (`PLUG-220`) that, when selected, runs the Skyshot program on the frame against the installed index, with the configured time limit and mode, writing its solution to a fresh temporary WCS file, and shall report failure with a reason (no solution, Skyshot's error text, timeout, program or index missing) rather than raising. It shall not rely on a position hint. | P2 |
| SKY-020 | A successful solve shall report the right ascension, declination, rotation and pixel scale of the **image centre** (J2000), computed through the WCS because Skyshot does not promise its reference pixel is the centre; the CD matrix shall be offered only when it is referenced to the centre. | P2 |
| SKY-030 | The plugin shall read the publisher's release manifest over HTTPS and accept it only if it is well-formed, has `schema_version` 1 and an `https` download folder, has valid archive names, sizes and SHA-256 values, and is compatible with the engine version the plugin targets. | P2 |
| SKY-040 | The plugin shall install an index only after its archive's size and SHA-256 match the manifest, shall accept only a flat folder of regular files (no links, traversal or extra levels) whose `bundle.json` matches the manifest, shall install each index atomically, and shall never overwrite or merge into an installed index. | P2 |
| SKY-050 | A download shall be cancellable and resumable; cancelling shall keep the partial file, and a corrupt download shall be discarded. | P2 |
| SKY-060 | The plugin's Options page shall state whether Skyshot is ready (program and index found), shall let the user set the solve mode and time limit (and shall never ask for the location of the program or index, `SKY-120`), and shall show the download size and required disk space and obtain confirmation before downloading. | P2 |
| SKY-070 | All plugin configuration shall be stored in the shared database through plugin settings (`PLUG-150`); stored values that are invalid shall fall back to safe defaults; the solver shall report itself ready only when both the program and an index are found. | P2 |
| SKY-080 | The plugin shall offer to download a prebuilt Skyshot program for the user's computer (Windows x64, Linux x64, Linux ARM64, macOS Apple silicon) only when one is pinned in the plugin, shall accept an archive only from a GitHub release URL and only if its SHA-256 equals the value pinned inside the plugin, shall discard one that does not match, and shall say plainly that the program is unsigned and ask before downloading. | P2 |
| SKY-090 | The plugin shall unpack the program only if every archive member is a plain file or folder beneath one expected root folder (no links, absolute or escaping paths, duplicates or implausible sizes), shall keep the licence and notice files with it, shall keep it only if it starts and reports its version, shall never overwrite an installed program, and shall look for the program in fixed places in the order: the plugin's `program` folder (a program built by hand), the downloaded program, `PATH`, cargo's install folder. | P2 |
| SKY-100 | The prebuilt programs shall be built unmodified by Galileo's CI from one pinned upstream commit on each target platform, using the upstream toolchain and packager, shall pass upstream's tests and its packaged smoke solve before publication, and shall be published only on request, with the SHA-256 list the plugin pins generated from the built archives. | P2 |
| SKY-110 | The plugin and its documentation shall credit Skyshot's author and licence (Apache License 2.0) and state that the plugin is not endorsed by Skyshot; shall keep Skyshot's licence and notice files with the downloaded program; shall tell the user, before an index download and on the Options page, that the index data has separate terms (described by its author as intended for non-commercial use) and which catalogues it derives from (ASTAP D80, ESA Gaia DR3); shall keep each index's `LICENSE-DATA.txt` with it and refuse an index archive that lacks one; and shall not redistribute index data itself. | P2 |
| SKY-120 | The plugin shall keep everything it downloads under one fixed folder inside Galileo's own data folder (the downloaded program, the star indexes, the download cache), shall show that location on its Options page with a button that opens it, shall offer a `program` folder in it for a program built by hand, and shall have no stored setting or input for the location of the program or index; paths stored by earlier versions shall be ignored. | P2 |
