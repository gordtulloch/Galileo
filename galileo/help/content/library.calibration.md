<!-- order: 71 -->
# Calibration

Calibration runs the auto-calibration command from inside Galileo: it analyses your calibration sessions, builds master frames, calibrates light frames and assesses quality. It is the same command as `galileo-auto-calibration` in a terminal.

Choose an **Operation**, set any parameters, then press **Run**. The command's output appears in the **Output** frame as it works. Parameters that the chosen operation would ignore are greyed out, and the **Command** line shows exactly what will be run.

## Operation

What to do:

- **All (complete workflow)**: the whole auto-calibration workflow. It has no dry run, so it makes changes straight away.
- **Analyze opportunities**: report which sessions are ready to become masters, and the calibration state of your light frames. Changes nothing.
- **Create masters**: build master calibration frames.
- **Calibrate light frames**: apply the masters to light frames.
- **Assess quality**: measure star sizes, star counts and noise, and save the results to the catalog.
- **Clear all masters**: permanently delete every master frame, including all files in the repository's Masters folder. You are asked to confirm unless **Dry run** is ticked.

## Session ID

Process only this session. Leave blank for all sessions.

## Minimum files

The fewest frames needed for a session to count as ready to become a master, used by **Analyze opportunities**. *From settings* uses the Library setting.

## Configuration file

An `.ini` file to take the Library settings from. Leave blank to use the settings under Options > Library.

## Log file

Where the command appends its log. Leave blank for `library.log` in Galileo's log folder.

## Browse...

Picks the file for the box beside it.

## Dry run

Show what would be done without changing anything. Offered for **Create masters**, **Calibrate light frames** and **Clear all masters**.

## Force

Recreate masters that already exist, or recalibrate frames that are already calibrated.

## Quality only

With **All**, only assess quality; no masters are made and nothing is calibrated.

## Quality report

The command accepts this switch (`--report`) but does not act on it yet, so it is greyed out.

## No cleanup

The command accepts this switch (`--no-cleanup`) but does not act on it yet, so it is greyed out.

## Verbose

Include detailed debugging messages.

## Quiet

Send messages only to the log file. The **Output** frame then shows little or nothing besides the result.

## Run

Starts the command. The parameters are locked until it ends. You can go to other screens while it runs.

## Stop

Ends the command immediately. A file being written at that moment may be left incomplete.

## Clear output

Empties the **Output** frame. The log file is not touched.

## Output

Everything the command prints, followed by whether it finished successfully.
