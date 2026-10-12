<!-- order: 17 -->
# History

History is where you review how a session went, frame by frame. Each time a session takes a light exposure, Galileo measures the stars in it and records the **HFR** (half-flux radius — smaller is sharper), the **star count** (a drop usually means cloud, dew or a drifting focus) and, when PHD2 is connected, the **guide RMS** in RA and Dec. Calibration frames are not recorded.

The chart plots HFR (blue, left axis) and star count (orange, right axis) against frame number; the table underneath lists every frame. Recording is saved when the session ends and survives restarts; a session that is still running updates here every few seconds.

Sessions are named after the session that produced them plus the date and time they started.

## Session

Chooses which recorded session to show, most recent first, with its frame count. The summary line above the chart gives the mean, best and worst HFR, the mean star count and, if guiding was running, the mean guide RMS.

## Refresh

Re-reads the recorded sessions. The page also does this itself when you open it and every few seconds while it is visible.

## Export CSV…

Saves the selected session's frames (timestamp, HFR, star count, guide RMS) as a CSV file for analysis in a spreadsheet or your own tools.

## Delete Session

Removes the selected session's recorded history after you confirm. The images themselves are not touched.
