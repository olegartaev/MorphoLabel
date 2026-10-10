# Changelog

## 1.0.0-rc.5 — 2026-10-10

- Added persistent specimen, sample, locality and source-file identities to scientific CSV exports, compatible TPS/MorphoJ specimen crosswalks, and sample/filename metadata to X-ray exports.

## 1.0.0-rc.4 — 2026-10-09

- Added a consistency check that aborts an analysis export if project definitions change while its database snapshot is prepared.

## 1.0.0-rc.3 — 2026-10-08

- Revalidated the Windows installer and installed application for release candidate 3.

## 1.0.0-rc.2 — 2026-10-08

- Completed deep release qualification and user-path GUI testing.
- Corrected scientific X-ray calculations and persistence behavior.
- Strengthened semantic model and scheme compatibility.
- Improved Landmark verification, draft and queue state consistency.
- Hardened portable Landmark and X-ray model roundtrips.
- Added Unicode-safe scientific exports.
- Improved frozen RTMPose training preflight isolation.
- Synchronized workflow counters after prediction, review and calibration.
- Applied final RC2 GUI and state fixes.

## 1.0.0-rc.1 — 2026-10-06

- Unified the MorphoLabel application around two production modules: Landmarks & Measurements and X-ray Traits.
- Kept each module's scientific state, models and work queues independent while sharing the managed AI runtime.
- Added portable trained-model import and export with project provenance.
- Hardened Crop and Landmark coordinate frames and preserved project source, correction and model history.
- Added quality-control and repeatability workflows across both modules.
- Completed first-run AI setup for Landmarks and X-ray, including verified component downloads with resume and retry.
- Added CPU/GPU/CUDA qualification and disposable prediction/training checks.
- Prepared the standalone Windows installer and validated release, architecture and compatibility contracts.

## 0.5.0-beta.8

- landmark training from legacy MorphoLabel RTMPose parents no longer inherits obsolete project-local `rtmpose_augmentations` imports;
- machine performance tuning cache now lives under MorphoLabel application state, so a clean uninstall is actually clean;
- uninstall removes the exact legacy SIMM performance-tuning cache left by older builds without deleting unrelated legacy data;
- About now credits development assistance from OpenAI Codex.


## 0.5.0-beta.7

- **Unverified AI review** now refreshes persisted review sessions to pending-only images and never reopens completed ranked sessions;
- AI review risk ranking preserves score separation instead of saturating top candidates into one tie, with more stable history-based calibration;
- **Final data QC** is explicitly separated from pre-verification AI review and reports landmark-distance, within-group measurement, and GPA/PCA shape checks more clearly;
- uninstall now removes MorphoLabel-owned AI/runtime/state/cache data while leaving scientific project folders untouched;
- finalized RTMPose training checkpoints and diagnostic logs are pruned to bounded retention;
- Crop training no longer depends on keeping every developed PNG cache file, and missing developed cache is rebuilt on demand;
- developed-image cache retention is bounded without mutating the scientific project database.


## 0.5.0-beta.6

- first-run AI setup names the exact runtime/model components and shows explicit staged progress to 100%;
- Landmark finite-review navigation uses **Verify & Next** with the same green verification icon;
- **Clear all** returns selection to the first landmark for immediate re-annotation;
- **Review worst** is strictly a pre-verification queue of complete unverified AI predictions and skips members verified after queue creation;
- **Complex QC** is now a distinct post-verification audit of final human-verified data;
- Review worst and Complex QC use equal-sized controls, distinct icons, and updated help text that explains their roles.


## 0.5.0-beta.5

- first launch explains the managed AI runtime and bootstrap model before any large download;
- AI support downloads require one explicit user action and can be deferred without repeated startup nagging;
- deferred installations cannot silently download the managed AI runtime on later AI use;
- AI setup can be started later from the AI menu, with resumable verified downloads and clear progress;
- compact UI icons are larger and easier to read without materially reducing the annotation workspace;
- source launch is resilient to broken or redirected Python user-site environments.


## 0.5.0-beta.4

- Landmarks workspace rendering no longer starts or downloads the AI runtime;
- first launch after installation visibly prepares managed AI support in the background;
- first-run setup downloads and verifies the AI runtime and bootstrap model when needed;
- first-run hardware qualification records CPU, RAM, GPU, VRAM and CUDA availability;
- a real inference and short training smoke test confirm that AI is usable on the machine;
- safe machine defaults are stored once, while project-specific performance tuning remains tied to real workloads.

## 0.5.0-beta.3

- resumable managed-AI downloads with retry and verified partial-file recovery;
- interrupted first-use AI installation no longer discards already downloaded data;
- release-candidate validation is performed before the public tag is created.

## 0.5.0-beta.2

- standalone Windows installer with clean install/uninstall checks;
- managed, versioned AI runtime with verified downloads, CUDA support and CPU fallback;
- module hub and extension-ready module architecture;
- portable project/state handling under the user application-data directory;
- improved crop, landmark, measurement, exclusion, queue and training-readiness consistency;
- privacy-conscious diagnostic ZIP reports for support;
- RAW-image support, distribution metadata, branding and release hardening.

## 0.5.0-beta.1

- release hardening for the first public beta;
- recursive discovery of nested source images in direct-layout projects;
- source availability is refreshed safely when projects reopen;
- reduced false-positive early landmark identity warnings;
- removed obsolete legacy UI surfaces;
- restored and modernized current regression coverage;
- project, crop, landmark, QC, lineage, exclusion, repeatability, measurement and export contracts revalidated.

## 0.5.0-beta

- initial public development beta;
- Landmarks & measurements module;
- provenance-preserving workflow;
- manual and AI-assisted landmark review;
- QC, measurements, and export.
