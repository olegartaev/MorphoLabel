# First-run verification

Run from the project root:

`python tools\e2e_selftest.py`

It scans sources read-only, checks hashes, makes one derived REVIEW-only master, writes deterministic queues/splits, verifies no split leakage, and exports the empty-or-human-final training and canonical CSV schemas. It never creates biological landmark coordinates.

Launch the application with `START_APP.cmd`.
