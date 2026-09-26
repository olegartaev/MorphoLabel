# Technical notes

The first runnable implementation uses Python's standard-library Tkinter GUI and JSON/CSV scientific records.  This keeps the initial application portable and makes all landmark records inspectable without a database.

`orig_photos` is never opened for writing. Source identity is a SHA-256 plus a relative path. Derived work is intended to live under `work/<sample>/`.

The current set consists primarily of Nikon NEF raw files. RAW rendering/standardization is deliberately optional (`Pillow`, `rawpy`, and `numpy`) rather than a hidden cloud or Ollama dependency. Until those packages are installed, the GUI reports preview unavailability rather than guessing or fabricating an image/crop.

The affine transform object records rotation and crop and provides exact inverse mapping. A future normalization backend must write this provenance and assign PASS/REVIEW/FAIL; it must never mirror or anatomically warp an image.

The AI adapter is intentionally unconfigured. It reserves RTMPose, HRNet, and ViTPose as candidates, but cannot train or label until genuine human annotations exist.
