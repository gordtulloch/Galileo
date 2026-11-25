# Video scripts

Narration scripts for the Galileo video series, written for amateur astrophotographers.

| # | Script | Minutes |
|---|---|---|
| 0 | [Quick start: first light](00-quick-start.md) | 10 |
| 1 | [Introduction and overview](01-introduction.md) | 30 |
| 2 | [Installation and equipment setup](02-installation-and-equipment.md) | 30 |
| 3 | [Star Atlas and planning](03-star-atlas-and-planning.md) | 30 |
| 4 | [Focusing, solving, guiding and imaging](04-focus-solve-guide-image.md) | 60 |
| 5 | [Automation with sessions and scheduling](05-automation-sessions-scheduling.md) | 30 |
| 6 | [Observatory safety and multi-Pier operation](06-observatory-safety-multi-pier.md) | 30 |
| 7 | [Using the Library](07-library.md) | 30 |
| 8 | [Plugins and the marketplace](08-plugins-and-marketplace.md) | 30 |
| 9 | [NodeConnect, WebConnect and outreach](09-nodeconnect-webconnect-outreach.md) | 30 |
| 10 | [MobileConnect and the iOS, Android and VR clients](10-mobileconnect-clients.md) | 30 |
| 11 | [Plugins for developers](11-writing-plugins.md) | 30 |

## Using a script

- Plain paragraphs are narration. Lines starting with `>` are production directions and `#` lines are chapter titles; neither is spoken.
- `> SCREEN:` says what to show. `> PAUSE: n` is n seconds of silent demonstration.
- Run `python docs/scripts/extract_narration.py` to write narration-only text to `narration/` and to see each running time. Add `--wpm` for your narrator's speed. Run it again after editing a script; do not edit `narration/` by hand.
- Running times assume 150 words per minute plus the pauses. The pauses are a large share of each episode (a quarter to a half, and about 60% in episode 6 and the quick start), so adjust them to the length of the recorded demonstrations.
- The narration-only text drops the pauses. Insert them in the video edit, or convert them to your narrator's own pause markup.

## Pronunciation

| Written | Say |
|---|---|
| INDI | "indy" |
| ASCOM | "ASS-com" |
| Alpaca | as the animal |
| ASTAP | "A-stap" |
| PHD 2 | "P H D two" |
| NGC, IC, FITS, XISF | "N G C", "I C", "fits", "ex-iss-eff" |
| M 31 | "M thirty-one" |

## Before recording

The scripts were written from the wiki, the inline help and the plugin READMEs and changelogs around version 0.9.09alpha. They have not been checked screen by screen against a running build, so follow each one in the application first. Pay particular attention to:

- What unsafe weather does (episodes 2, 5 and 6): updated 2026-11-25 for the protective stop (SRS `SAFE-130` to `SAFE-180`). Rehearse it on simulators and your own equipment before recording.
- Scheduled sessions starting on every connected Pier follows the code and `OBS-140`; the Schedule inline help still says only the Pier in the top bar.
- The state of NodeConnect, WebConnect, MobileConnect, Quest and outreach (episodes 9 and 10), which changes quickly, and how to obtain the apps.
- Whether installing a plugin needs a restart. The inline help and the plugin READMEs differ.
- Anything the script describes as untested on real hardware.
