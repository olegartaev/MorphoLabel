# Changelog

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
