# MorphoLabel

Scientific software for image-based biological morphology with AI-assisted annotation, quality control and reproducible analysis.

**Release: 1.0.0-rc.1**

MorphoLabel keeps projects and their source-image references, annotations, model history and processing records together so analyses can be reviewed and repeated.

## Production modules

### Landmarks & Measurements

- Prepare specimen crops and review standardized images.
- Annotate landmarks manually or use AI prediction and training.
- Verify annotations and inspect quality-control and repeatability results.
- Calibrate samples, calculate measurements and export results with project provenance.

### X-ray Traits

- Create specimen crops from X-ray plates and set specimen orientation.
- Annotate skeletal structures manually or use Structure AI prediction and training.
- Review traits, quality-control findings and repeatability records.
- Export project results with their annotation and model provenance.

Each module keeps its scientific project state, models and work queues independent.

## Installation

MorphoLabel runs on **Windows 10/11 x64**. Most users only need [`MorphoLabel-1.0.0-rc.1-Setup-x64.exe`](https://github.com/olegartaev/MorphoLabel/releases/download/v1.0.0-rc.1/MorphoLabel-1.0.0-rc.1-Setup-x64.exe). No Python, Git or manually installed packages are required.

On first launch, you can review and install AI support. Setup lists each component and shows download progress. Interrupted downloads can resume; required files are verified before use. MorphoLabel checks available CPU, GPU and CUDA support, then qualifies prediction and training. Landmarks and X-ray use one managed AI runtime. AI setup does not upload research images or project data.

The application also runs without installing AI support; you can continue without AI and set it up later from the AI menu.

## Scientific provenance and data safety

Projects preserve source references and hashes, processing details, coordinate transforms, review state, model provenance and software version. Keep research projects in user-selected folders. Do not add private project databases, research images, credentials or generated reports to this repository.

## Release status

`1.0.0-rc.1` is the release candidate for MorphoLabel 1.0. Core workflows, the installer, project persistence and AI setup have completed pre-release validation.

## Citation

Use [`CITATION.cff`](CITATION.cff) for citation metadata. Please identify MorphoLabel as the source when citing results produced with the software.

## License

MorphoLabel is released under the [Apache License 2.0](LICENSE). See [`NOTICE`](NOTICE) for attribution information.

## Development

For source development, use Python 3.11 on Windows 10/11 x64. Start the application with `START_APP.vbs` or `python -m app`; see [`CONTRIBUTING.md`](CONTRIBUTING.md) before proposing changes.

## Contact

Project questions: morpholabel@olegartaev.com
