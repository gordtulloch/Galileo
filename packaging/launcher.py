# SPDX-License-Identifier: GPL-3.0-or-later
"""PyInstaller entry point.

Freezing galileo/app.py directly would make it the top-level script, so its ``__file__`` (used to
locate ``assets/``) would resolve outside the bundle's package tree.  Importing it as a module keeps
``galileo.app.__file__`` at ``<bundle>/galileo/app.pyc``, so ``<bundle>/assets`` is found.
"""
from galileo.app import main

if __name__ == "__main__":
    main()
