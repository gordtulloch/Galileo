# Contributing to Galileo

Thank you for wanting to help. Galileo is licensed under [GPL-3.0-or-later](LICENSE), and the maintainer also offers a Pro edition with added features and support. To keep both possible, **every contribution needs a signed Contributor License Agreement (CLA)** — see [How to sign](#how-to-sign) and the [agreement itself](#contributor-license-agreement) below.

## Before you start

- **Open an issue first** for anything larger than a small fix, so effort isn't spent on something that won't be merged.
- **Read the design documents.** [`docs/SRS.md`](docs/SRS.md) lists the numbered requirements, and [`docs/SDD.md`](docs/SDD.md) describes the architecture. Architectural changes should follow them.
- **Stay behind the port interfaces.** The domain core and the UI must never import `galileo.adapters.indi` or `galileo.adapters.alpaca` directly; they use the port interfaces in `galileo.core.devices`. Modules talk to each other through the event bus (`galileo.bus`), not by direct calls.

## Development setup

Requires Python 3.11 or newer.

```bash
pip install -e ".[test,dev]"
pytest -m "not soak and not hardware and not integration"   # fast run
ruff check .
mypy .
```

## What a pull request should contain

1. **Tests.** Tests are organised by SRS requirement domain, one file per domain (for example `tests/test_arch.py` covers `ARCH-*`). Add one `test_tc_<domain>_<nnn>_<description>` function per test case ID, tagged with `@pytest.mark.requirement("TC-...")` and `@pytest.mark.priority("MVP" | "P2" | "P3")`, with a docstring starting with the requirement ID. Reserved test case IDs are in [`docs/RTM.md`](docs/RTM.md). Device interaction is tested against the mocks in `tests/conftest.py`; only `hardware`-marked tests touch real devices.
2. **A `CHANGELOG.md` entry** under `## [Unreleased]`, in the right `Added` / `Changed` / `Fixed` / `Removed` section (older entries live in [`docs/changelog/`](docs/changelog/); add new ones only to the root file). Write it for someone who wasn't watching: say what changed and why it matters, not a diff summary.
3. **A file header on every new Python file**, exactly:
   ```python
   # SPDX-License-Identifier: GPL-3.0-or-later
   # Copyright (C) <year> <your name>
   ```
   Contributors keep the copyright in their own contributions (see the CLA). Do not remove or alter existing notices.
4. **Doc updates** where behaviour changes: the SDD section for the module and, if requirements change, the SRS and RTM.

## How to sign

**Individuals.** Read the agreement below. Then, on your first pull request, add a comment containing exactly:

> I have read the Galileo Contributor License Agreement, version 1.0, and I agree to its terms for this and all my past and future Contributions to Galileo.

The maintainer records your GitHub username, the date and the CLA version, and will not merge a pull request until that is on record.

**Companies.** If your employer might own what you write (many employment contracts say so), your employer must agree too. Ask them to email the maintainer a statement that they have read the CLA, waive any rights in your Contributions, or agree to its terms, and that names the people authorised to contribute. Do not submit code until that is on record.

**Trivial changes.** Typo and one-line documentation fixes still need the CLA if you want them merged; the maintainer may instead make such a fix themselves.

---

# Contributor License Agreement

**Galileo Contributor License Agreement — version 1.0**

This agreement is between you ("**You**") and Gord Tulloch ("**the Maintainer**"), and covers everything you contribute to Galileo. You agree to it by commenting as described in [How to sign](#how-to-sign).

## 1. Definitions

- "**Galileo**" means the software project at <https://github.com/gordtulloch/Galileo> and every edition of it published by the Maintainer, including the GPL-3.0-or-later edition and any Pro or commercial edition.
- "**Contribution**" means any code, documentation, data, artwork or other material that You intentionally submit to the Maintainer for inclusion in Galileo, whether by pull request, patch, issue, email or any other means, other than material You mark clearly in writing as "Not a Contribution."

## 2. You keep your copyright

You keep the ownership of your Contributions. This agreement does not take it from You, and You remain free to use your own Contributions elsewhere.

## 3. Copyright licence to the Maintainer

You grant the Maintainer a perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable copyright licence to reproduce, prepare derivative works of, publicly display, publicly perform, distribute, **sublicense and relicense** your Contributions and derivative works of them, **under any licence terms of the Maintainer's choosing, including proprietary and commercial terms**.

## 4. Moral rights

To the extent the law allows, You waive, and agree not to assert against the Maintainer, the Maintainer's licensees and their successors, any moral rights (including rights of attribution and integrity) You hold in your Contributions. Where a waiver isn't permitted, You grant the Maintainer the broadest permission the law allows to use, modify and adapt your Contributions without attributing them to You. The Maintainer will keep your name in the project's history and in any file header You supply.

## 5. Patent licence

You grant the Maintainer and everyone who receives Galileo a perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable patent licence to make, have made, use, offer to sell, sell, import and otherwise transfer your Contributions, alone or combined with Galileo, under any patent claims You own or control that are necessarily infringed by your Contribution alone or in combination with Galileo. If anyone sues You alleging that your Contribution or Galileo infringes a patent, the patent licence You granted for that Contribution ends on the date the suit is filed.

## 6. Public licence commitment

Contributions included in a release of the GPL-3.0-or-later edition of Galileo remain available under GPL-3.0-or-later. Nothing in this agreement lets the Maintainer withdraw that release or take away rights already granted to recipients of it.

## 7. What You promise

You promise that:

1. each Contribution is your original creation, or You have the right to submit it under this agreement;
2. You have the legal authority to grant the rights in this agreement, and if your employer or anyone else has rights in your Contributions, You have received their permission or a waiver, as described in [How to sign](#how-to-sign);
3. your Contribution does not, to your knowledge, infringe anyone's rights, and does not contain code or other material under a licence that is incompatible with GPL-3.0-or-later or with the Maintainer's right to relicense it under Section 3; and
4. if You include third-party material, You will say so in the pull request, identify its source and licence, and mark it "Not a Contribution" so the Maintainer can decide whether to accept it.

You will tell the Maintainer if any of these promises stops being true.

## 8. No obligation, no warranty

The Maintainer doesn't have to accept, keep or release any Contribution. Except for the promises in Section 7 (which You make in good faith), You provide Contributions "as is," without warranties or conditions of any kind, including title, non-infringement, merchantability or fitness for a particular purpose.

## 9. Changes to this agreement

The Maintainer may publish new versions of this agreement. A new version applies only to Contributions You make after You agree to it. Your agreement to version 1.0 continues to cover everything You contributed while it was in force.

## 10. Governing law

This agreement is governed by the laws of the Province of Manitoba and the federal laws of Canada that apply there, without regard to conflict-of-laws rules. You and the Maintainer submit to the jurisdiction of the courts of Manitoba for any dispute arising from it.

## 11. Entire agreement

This is the whole agreement between You and the Maintainer about your Contributions. If a court finds part of it unenforceable, the rest stays in force.
