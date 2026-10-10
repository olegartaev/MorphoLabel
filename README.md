# MorphoLabel

**Open-source software for standardized, large-scale processing of biological images into morphological data, with human verification and optional AI assistance.**

MorphoLabel is designed for collections of hundreds or thousands of photographs or radiographs. Its purpose is to apply **one biologically defined annotation scheme and a consistent procedure across an entire dataset**, while retaining links to specimen identity, source images, human decisions, AI models (if used) and exported results.

The central idea is **stage-by-stage, human-in-the-loop mass annotation**. Instead of completing every operation for one specimen before starting the next, researchers can prepare Crops across a collection, then annotate landmarks or anatomical structures across the prepared specimens, review the resulting measurements or traits and export a controlled dataset. Manual processing is fully supported; optional AI can accelerate repetitive work within each stage.

**Current release:** [MorphoLabel 1.0.0-rc.5](https://github.com/olegartaev/MorphoLabel/releases/tag/v1.0.0-rc.5) · Windows 10/11 x64 · Apache-2.0

[Download installer](https://github.com/olegartaev/MorphoLabel/releases/download/v1.0.0-rc.5/MorphoLabel-1.0.0-rc.5-Setup-x64.exe) · [Full User Guide](docs/USER_GUIDE.md) · [Changelog](CHANGELOG.md) · [Citation](CITATION.cff)

---

## Why MorphoLabel

Modern imaging can produce photographs and radiographs much faster than a researcher can turn them into measurements, landmark coordinates or anatomical counts. The limiting step is often not image acquisition but **consistent annotation, review and conversion of images into structured data for downstream analysis**.

MorphoLabel addresses that bottleneck by combining:

- structured projects and reusable biological annotation schemes;
- stage-by-stage and batch-oriented processing across large image collections;
- manual scientific annotation;
- reusable annotation and trait schemes;
- project-specific AI training and prediction;
- explicit human verification;
- repeatability assessment;
- targeted quality-control queues;
- model and annotation provenance;
- transparent export formats for downstream analysis, with review and provenance retained in the project.

AI is optional. The software remains usable as a manual annotation system, and AI predictions are treated as proposals that can be corrected and verified by the researcher.

## Work by stage across the collection

**The unit of work is a collection or batch, not a separate end-to-end workflow for every image.** Standardizing framing, orientation and anatomical definitions before mass annotation helps limit variation introduced by the processing procedure itself.

- **Landmarks & Measurements:** define one landmark scheme → prepare or confirm Crops across the relevant images (**optional** when the source images are already standardized) → place and verify landmarks across those images → define/calibrate linear measurements → run final QC and export.
- **X-ray Traits:** define one anatomical trait scheme → identify, orient and confirm specimen Crops across the X-ray plates → mark and verify structures (for example, vertebrae) across the cropped specimens → inspect calculated traits → run final QC and export.

Within a stage, work manually or train a model on a representative verified batch and use it to predict and review the remaining eligible images. This is a **recommended scientific workflow, not a rigid lock**: individual records can be revisited, and corrections made in an earlier stage remain linked to later work. For a large dataset, the practical pattern is **all relevant Crops first, then all relevant landmarks or structures**, rather than repeatedly switching stages for each specimen.

## Production modules

<table>
<tr>
<td width="50%" valign="top">

### Landmarks & Measurements

<img src="app/resources/module_covers/landmarks.png" alt="Landmarks and Measurements module" width="100%">

For collections of photographs or other biological images in which the same anatomical landmarks and linear measurements are recorded across many specimens.

Key workflows:

- optional specimen Crop and orientation standardization;
- manual landmark placement;
- explicit missing-landmark states;
- geometric-morphometric landmark sets;
- human repeatability;
- AI-assisted landmark prediction;
- review of unverified AI annotations;
- final QC of verified data;
- calibration of linear measurements to millimetres when image scales permit;
- landmark-to-landmark measurements;
- TPS, CSV and MorphoJ-compatible export.

</td>
<td width="50%" valign="top">

### X-ray Traits

<img src="app/resources/module_covers/xray_traits.png" alt="X-ray Traits module" width="100%">

For radiographic collections containing one or more specimens per plate, where repeated anatomical structures and reference marks are annotated consistently to calculate biological traits. The current workflows are particularly suited to oriented specimens and skeletal counts.

Key workflows:

- specimen detection and Crop on X-ray plates;
- standardized head/ventral orientation;
- repeated-element and reference-marker annotation;
- configurable trait schemes that are not hard-coded to a single taxon;
- counts, positions, normalized image-space distances, angles and derived traits;
- structure visibility states;
- human repeatability;
- Crop AI and Structure AI;
- suspicious-result review;
- verified-only trait export.

</td>
</tr>
</table>

## Interface

These screenshots illustrate real biological annotation workflows from an earlier release candidate; cosmetic details may differ in newer builds.

### Landmarks & Measurements

<img src="docs/images/landmarks-workspace.webp" alt="MorphoLabel Landmarks and Measurements workspace showing a fish specimen with anatomical landmarks and the human-in-the-loop prediction and review workflow" width="100%">

*Landmark annotation workspace: specimen navigation, anatomical landmark scheme, human verification, AI prediction/review and final data QC.*

### X-ray Traits

<img src="docs/images/xray-structures-workspace.webp" alt="MorphoLabel X-ray Traits Structures workspace showing numbered vertebrae, reference markers, pterygiophores and the prediction and review workflow" width="100%">

*X-ray Structures workspace: repeated-element annotation, anatomical reference markers, human-reviewed AI output, prediction/review controls and result checking.*

## Typical workflow

1. **Set up the dataset:** create a project, connect the images and define stable specimen identities and a biologically meaningful scheme.
2. **Process the Crop stage across the collection:** frame and orient the relevant specimens, using manual work or AI-assisted batches. Crop is optional for already standardized Landmarks images.
3. **Process the annotation stage across the prepared specimens:** place and verify Landmarks or X-ray Structures according to the same scheme. Use representative human-verified batches to train optional AI, then review its predictions.
4. **Obtain biological variables:** derive landmark-to-landmark measurements or calculate X-ray traits from the annotations.
5. **Check consistency and quality:** use Human Repeatability where appropriate, review suspicious records and correct them at the appropriate stage.
6. **Export the intended dataset:** select the verified subset where available, and keep specimen identities, definitions and provenance with the scientific results.

This is a recommended order for efficient large-scale work; incomplete batches and individual corrections can be handled without restarting the whole project.

For a complete step-by-step workflow, see the **[MorphoLabel User Guide](docs/USER_GUIDE.md)**.

## Human verification is the core of the workflow

MorphoLabel distinguishes between a machine-generated draft and data that a researcher has reviewed and accepted within the current project.

- AI predictions remain reviewable until the user confirms them.
- A **Verified** state means that the annotation has been human-reviewed within the current scheme; it is not, by itself, proof that the landmark definition, homology, image quality or biological interpretation is correct.
- Verified human annotations are protected from routine batch prediction.
- Manual corrections remain part of the project history.
- Review queues help direct attention to pending or suspicious cases rather than forcing the user to re-check the whole dataset.
- Repeatability workflows estimate the consistency of the human annotation process itself.

This design is intended for scientific datasets where traceability and explicit review are more important than maximizing unattended automation.

## AI support

MorphoLabel can train and apply models for Crop, Landmarks and X-ray Structures.

On first launch, AI support can be installed through the guided setup. The application:

- lists the AI components before download;
- keeps one managed AI runtime shared by the production modules;
- checks CPU, GPU, VRAM and CUDA availability;
- verifies the installed components;
- supports resumable downloads;
- can run without AI if setup is deferred.

AI setup and processing are local. The setup process does **not** upload project images or scientific data.

Trained models can be selected, compared, imported and exported so that a validated model can be reused on another compatible project or computer.

## Reproducibility support and data safety

MorphoLabel is built around persistent project state rather than one-off image editing.

Projects preserve, where applicable:

- references to source images and source hashes;
- Crop geometry and orientation;
- landmark or structure annotations;
- human-verification state;
- excluded-item state;
- model identity and prediction provenance;
- annotation and correction history;
- repeatability records;
- QC/review state;
- calibration and measurement definitions;
- software and workflow metadata used for export.

Original source images are not edited by normal annotation operations. X-ray projects can also be made self-contained by copying source radiographs into the project.

**Recommendation:** back up the complete MorphoLabel project folder together with any externally referenced source-image folders.

## Installation

MorphoLabel currently targets **Windows 10/11 x64**.

Most users only need the standalone installer:

**[MorphoLabel-1.0.0-rc.5-Setup-x64.exe](https://github.com/olegartaev/MorphoLabel/releases/download/v1.0.0-rc.5/MorphoLabel-1.0.0-rc.5-Setup-x64.exe)**

No separate Python or Git installation is required for normal use.

The optional AI components are downloaded by MorphoLabel when AI support is installed. The large AI release assets are not intended for manual installation.

## Outputs

Depending on the module and project configuration, MorphoLabel can produce:

- landmark coordinates in TPS;
- landmark coordinates in wide or long CSV;
- MorphoJ-compatible coordinate text;
- calibrated linear measurements in CSV or tab-delimited text;
- a verified-only **analysis dataset bundle** with specimen identities, landmark and measurement tables, definitions and missing-value/omission reports;
- X-ray trait tables in CSV;
- verified-only X-ray trait exports;
- portable trained-model packages;
- diagnostic ZIP reports for technical support.

**Export note:** for Landmarks & Measurements, use **Export analysis dataset… → Verified only (default)** to prepare a reviewed analysis bundle; direct TPS/CSV/MorphoJ and measurement exports may include eligible unverified records. In X-ray Traits, the trait-table exporter also offers **Verified only**. Verification records human review, not proof of biological validity.

## Intended use

MorphoLabel is intended for researchers working with repeatable morphology-from-image workflows, including:

- geometric morphometrics;
- linear morphometrics derived from landmarks;
- skeletal counts and meristic traits;
- radiographic datasets;
- museum and field image collections;
- taxonomic and comparative morphology;
- projects where annotation consistency and auditability are important.

It is not a substitute for biological definition of landmarks or traits. The researcher remains responsible for defining homologous structures, choosing an appropriate sampling design, reviewing annotations and interpreting the resulting data.

For geometric morphometrics, MorphoLabel prepares landmark-coordinate data; it does not replace downstream procedures such as Generalized Procrustes Analysis, shape statistics or biological interpretation in software such as MorphoJ, R or other analytical environments.

## Release status

1.0.0-rc.5 is release candidate 5 for MorphoLabel 1.0. It includes unified specimen identity metadata in scientific analysis exports and is intended for external acceptance before the stable 1.0.0 release.

For routine usage questions, open **Menu → Help with an AI assistant…** to copy a question template referencing the public User Guide and source code. Paste it into an external AI assistant of your choice; verify scientific advice and do not share confidential research data.

If you encounter a reproducible technical problem, use **Menu → Create diagnostic report…**. The diagnostic ZIP is designed not to include research photographs or the project SQLite database.

For newer builds and current release notes, visit the [Releases page](https://github.com/olegartaev/MorphoLabel/releases).

## Documentation

- **[Full User Guide](docs/USER_GUIDE.md)** — installation, concepts, complete workflows, AI, QC, export and troubleshooting.
- [Changelog](CHANGELOG.md) — release history.
- [Contributing](CONTRIBUTING.md) — source-development guidance.
- [Extension architecture](docs/EXTENSIONS.md) — module-extension design.
- [Security](SECURITY.md) — security reporting.

## Citation

Citation metadata are provided in [CITATION.cff](CITATION.cff).

When MorphoLabel or a model substantially based on it contributes to published research, please identify MorphoLabel as the software source and cite the version used.

## License

MorphoLabel is released under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attribution information.

## Development

Source development currently targets Python 3.11 on Windows 10/11 x64.

Run START_APP.vbs, or from a Python environment use:

    python -m app

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing code changes.

## Contact

Scientific or software questions: **morpholabel@olegartaev.com**
