# Third-party notices

Galileo is licensed GPL-3.0-or-later (see [`LICENSE`](LICENSE)). The prebuilt installers also contain the
following components under their own licences.

## tetra3

- Source: <https://github.com/esa/tetra3>
- Copyright the European Space Agency; licensed under the Apache License 2.0
  ([`licenses/tetra3-LICENSE.txt`](licenses/tetra3-LICENSE.txt)).
- Used unmodified, as an optional plate-solving backend (Options > Solve). The installers include its default
  star-pattern database, which is built from the Hipparcos and Tycho catalogues.

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

Apache-2.0, MIT and GPL-2.0-or-later are compatible with Galileo's GPL-3.0 licence; the other dependencies' licences are recorded in their
own package metadata.
