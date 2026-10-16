<!-- order: 65 -->
# Dashboard

The Dashboard shows every Pier of the selected Observatory on one screen: what its equipment is doing, whether a session is running on it, and what is waiting in its job queue. Use it to keep an eye on a multi-Pier Observatory without switching between Piers; the other screens remain the focused, single-Pier view.

It updates by itself every couple of seconds while it is on screen, without slowing the rest of Galileo down. Double-click a Pier to make it the working Pier.

## Pier

The Pier's name. The Pier currently selected in the top bar is marked *(selected)*.

## Equipment

Whether the Pier's devices are *connected* or *disconnected*. Each Pier keeps its own connections, so a Pier you are not looking at still reads *connected* while any of its devices is. A Pier you have not connected since Galileo started reads *disconnected*, and its scheduled sessions wait until its camera or mount is connected.

## Sequence

The state of the session running on the Pier: *idle* when nothing is running, otherwise *running*, *paused*, *completed*, *stopped* or *error*.

## Scheduler

The Pier's job queue: *running:* followed by the job being executed (and how many more are waiting), or *N queued* when jobs are waiting for their start time, or *idle* when the queue is empty.

## Open Pier

Makes the highlighted Pier the working Pier — the same as choosing it in the top bar — so the other screens show and control it. Double-clicking a row does the same.
