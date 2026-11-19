# Third-party notices

Galileo is licensed GPL-3.0-or-later (see [`LICENSE`](LICENSE)). The prebuilt installers also contain the
following components under their own licences.

## tetra3

- Source: <https://github.com/esa/tetra3>
- Copyright the European Space Agency; licensed under the Apache License 2.0
  ([`licenses/tetra3-LICENSE.txt`](licenses/tetra3-LICENSE.txt)).
- Used unmodified, as an optional plate-solving backend (Options > Solve). The installers include its default
  star-pattern database, which is built from the Hipparcos and Tycho catalogues.

## Skyshot Solver (optional plugin; not bundled)

- Source: <https://github.com/ashtree74/skyshot-solver>
- Copyright 2026 Adam Jesionkiewicz; licensed under the Apache License 2.0.
- Not included in Galileo's installers or in the `skyshot_solver` plugin's ZIP. The plugin
  (`Galileo-Plugins/skyshot_solver`) downloads unmodified builds of the program, made by a GitHub Actions
  workflow from one pinned upstream commit. Each archive carries Skyshot's `LICENSE`, `NOTICE` and
  `third_party/` notices (covering its Rust dependencies and the Rust standard library) and the plugin keeps
  them beside the program. Galileo runs it as a separate program and does not link to it.
- The plugin's index-installer (`skyshot_solver/data.py`) is an independent reimplementation that follows the
  rules of Skyshot's `tools/install_data.py` and `tools/fetch_data.py` (archive checksum, flat archive layout,
  never overwrite an installed index). No code from those files is included; the file carries an attribution
  note.
- **Star indexes are separate from the code and have their own terms.** Skyshot's author describes them as
  intended for non-commercial use, derived from the ASTAP D80 star catalogue (<https://www.hnsky.org/astap.htm>),
  which is built from ESA's Gaia DR3 (Gaia data: ESA/Gaia/DPAC;
  <https://www.cosmos.esa.int/web/gaia/dr3>). They are downloaded by the user from Skyshot's own site, not
  redistributed by Galileo, and each keeps its `LICENSE-DATA.txt` and `PROVENANCE.json`; the plugin refuses an
  index that lacks a licence file. Whoever uses an index is responsible for complying with those terms.
- The plugin is not part of Skyshot and is not endorsed by its author.

## xisfits

- Source: <https://github.com/vrruiz/xisfits>
- Copyright (c) 2019 Víctor R. Ruiz; licensed under the MIT License
  ([`licenses/xisfits-LICENSE.txt`](licenses/xisfits-LICENSE.txt)).
- The XISF-to-FITS converter in `galileo/library/file_formats/xisfFile/` is a Python reimplementation whose
  structure (geometry and sample-format types, header fields, read/decompress/unshuffle pipeline) follows
  `xisfits`. No `xisfits` code is bundled; the files carry a "portions derived from" notice.

## KStars / Ekos

- Source: <https://invent.kde.org/education/kstars>
- `kstars/ekos/align/polaralign.cpp`: Copyright 2021 Hy Murveit; licensed GPL-2.0-or-later.
- The live-update knob model in `galileo/polaralign.py` (`knob_adjustment`, `axis_after_adjustment`, the
  rotation helpers) is derived from `PolarAlign::processRefreshCoords` and `findSmallestThetaY`, translated to
  Python and modified. No other KStars code is included. GPL-2.0-or-later is used here under GPL-3.0-or-later.
- Other KStars/Ekos features were used only as functional references; no code was taken from them. This covers
  the hold-to-move mount pad, the scheduler (`galileo/scheduler.py`), autofocus (`galileo/autofocus.py`),
  guiding (`galileo/guiding.py`, which follows the PHD2 event protocol, not KStars' client) and the meridian
  flip service (`galileo/meridianflip.py`). A source comparison found no copied code or comments.

Apache-2.0, MIT and GPL-2.0-or-later are compatible with Galileo's GPL-3.0 licence; the other dependencies' licences are recorded in their own package metadata.
