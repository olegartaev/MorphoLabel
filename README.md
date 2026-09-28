# MorphoLabel

Development beta · 0.5.0-beta.5

Open-source scientific software for biological morphology annotation, AI-assisted landmarking, quality control, measurements, and reproducible export.

## What MorphoLabel does

MorphoLabel provides a portable Windows workflow for organizing specimen images, reviewing standardized images, recording landmarks and calibration, checking annotations, and exporting provenance-preserving results. Original photographs and human-corrected landmarks remain under the operator's control.

## Current module

The active module is **Landmarks & measurements**. It opens from the module hub and supports project setup, image review, landmark annotation, calibration, review queues, AI-assisted workflows, and export.

## Key capabilities

- relative-path project storage with source hashes and provenance;
- manual landmarks with explicit missing states, correction history, and autosave;
- reversible image-frame metadata and QC/review states;
- sample calibration and measurement workflows;
- replaceable AI training/inference integration;
- human-readable CSV/JSON exports.

## Installation

### Windows

The public Windows distribution is built as a standalone application: users do not need Python, Git, pip, or PATH changes.

1. Open GitHub Releases.
2. Download the MorphoLabel Setup executable for the current beta.
3. Run the installer.
4. Start **MorphoLabel** from the Start Menu (or the optional desktop shortcut).

RAW decoding is bundled in the Windows application. On first launch, MorphoLabel explains the optional AI support before any large download begins. One explicit **Install AI support** action authorizes the versioned managed AI runtime and official bootstrap model; both are checksum-verified, followed by CPU/RAM/GPU/VRAM/CUDA detection, a real inference test and a short training qualification. The user can instead continue without AI and start setup later from the AI menu. No large AI component is downloaded silently. Workload-specific batch and worker tuning is measured later on real project images.

### Development from source

For development, use Python 3.11 on Windows 10/11 x64. The quickest supported source launch is:

```text
RUN_CANONICAL.cmd shell
```

If the current Python cannot see the core packages, this source-only launcher creates the gitignored repo-local `.venv` and installs `requirements.txt` there before starting. It does not modify the public installed build or project data. Manual setup is still possible:

```text
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m app
```

The application starts in the MorphoLabel Module Hub. Keep project data outside version control; see [data safety](.gitignore).

## Typical workflow

1. Create or open a project and select a specimen image source.
2. Review or correct the standardized image and QC state.
3. Calibrate the sample when measurements are required.
4. Place, correct, or mark landmarks missing; every scientific coordinate retains provenance.
5. Review QC and AI-assisted suggestions with human correction as the final authority.
6. Export landmarks, measurements, and reports from the project.

## AI and hardware requirements

The base application runs without cloud services or Ollama. Tagged Windows releases use a versioned managed AI component containing the pinned Python/PyTorch/OpenMMLab runtime and RTMPose configuration; users do not install Python packages manually. The upstream AP-10K bootstrap checkpoint is not redistributed by MorphoLabel: on first bootstrap use it is downloaded directly from OpenMMLab and accepted only after its pinned SHA256 is verified. GPU acceleration is used when the managed PyTorch runtime and local NVIDIA driver report CUDA availability, with CPU fallback retained.

## Scientific reproducibility and provenance

Projects record relative source paths, source hashes, processing metadata, coordinate transforms, review state, and software version. Do not add original photographs, private project databases, model weights, credentials, or generated reports to this repository.

## Current beta limitations

This is a development beta. The Windows installer, managed AI component, representative GUI workflows, and clean uninstall path have been validated; workflows and interfaces may still change before a stable release.

## Citation

Use [`CITATION.cff`](CITATION.cff) for the machine-readable citation metadata.

## License

MorphoLabel is released under the [Apache License 2.0](LICENSE). See [`NOTICE`](NOTICE) for attribution information.

## Contributing and issues

Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening an issue or pull request. Do not include private scientific data or credentials in issues, pull requests, or test fixtures.

## Contact

For project questions: morpholabel@olegartaev.com
