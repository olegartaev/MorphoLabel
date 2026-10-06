# MorphoLabel User Guide

This guide describes the scientific logic of MorphoLabel and the recommended way to use the program for large image-annotation projects.

MorphoLabel has two production modules:

- **Landmarks & Measurements** — landmark-based morphology, geometric morphometrics and linear measurements.
- **X-ray Traits** — specimen crops, skeletal markers and biological traits derived from radiographs.

Both modules follow the same principle:

**human reference → optional AI assistance → human verification → quality control → reproducible export**

The goal is not to remove the researcher from annotation. The goal is to make large annotation projects faster, more consistent and easier to audit.

---

## Contents

1. [What MorphoLabel is for](#1-what-morpholabel-is-for)
2. [Core concepts](#2-core-concepts)
3. [Installation and first launch](#3-installation-and-first-launch)
4. [General interface logic](#4-general-interface-logic)
5. [Landmarks & Measurements: complete workflow](#5-landmarks--measurements-complete-workflow)
6. [X-ray Traits: complete workflow](#6-x-ray-traits-complete-workflow)
7. [AI models and model management](#7-ai-models-and-model-management)
8. [Repeatability and quality control](#8-repeatability-and-quality-control)
9. [Working efficiently with large datasets](#9-working-efficiently-with-large-datasets)
10. [Data safety, provenance and backup](#10-data-safety-provenance-and-backup)
11. [Export and downstream analysis](#11-export-and-downstream-analysis)
12. [Troubleshooting and support](#12-troubleshooting-and-support)
13. [Scientific limitations and good practice](#13-scientific-limitations-and-good-practice)

---

# 1. What MorphoLabel is for

Biological imaging scales easily: a field season, museum visit, radiographic survey or automated imaging workflow can generate hundreds or thousands of images. The difficult part is often converting those images into consistent biological variables.

MorphoLabel is designed for this conversion step.

It organizes a project so that the following remain connected:

- the source image;
- the specimen or image identity;
- the annotation scheme;
- the human annotation;
- AI predictions, if used;
- the model that produced a prediction;
- later human corrections;
- verification state;
- repeatability records;
- quality-control findings;
- final exported values.

This matters because a table of final coordinates or counts is only the end product. For scientific work, it is also important to know how those values were produced and reviewed.

MorphoLabel therefore treats annotation as a workflow rather than as drawing points on images.

## 1.1 What “mass annotation” means here

Mass annotation does **not** mean blindly applying a model to all images.

In MorphoLabel it means that the repetitive parts of a large project are structured:

1. define a consistent biological scheme;
2. create a relatively small set of high-quality human examples;
3. verify them;
4. train an optional model;
5. predict new images in batches;
6. focus human effort on review and correction;
7. keep already verified work protected;
8. export the scientifically appropriate subset.

This is especially useful when most new images are routine but a minority are difficult, unusual or ambiguous.

---

# 2. Core concepts

Understanding a few terms makes the whole program easier to use.

## 2.1 Project

A **project** is the persistent scientific workspace. It stores the project configuration, annotations, review state, models and other workflow information.

Use a separate project when the biological annotation scheme, source collection or scientific purpose is substantially different.

## 2.2 Source image

The **source image** is the original photograph or X-ray used as evidence.

Normal MorphoLabel annotation operations do not modify the original source image. Cropping, orientation and display transformations are stored as project information.

## 2.3 Crop

A **Crop** defines the working view of a specimen.

In the Landmarks module, Crop is optional. You can standardize specimens before landmarking or skip Crop and work directly on the source images.

In the X-ray module, a plate can contain several specimens. Each specimen receives its own Crop. Crop also records orientation.

## 2.4 Annotation

An annotation is a human- or AI-created mark associated with a biological definition.

Examples include:

- an anatomical landmark;
- a vertebral marker;
- a reference point used as a counting boundary.

Annotations are not meaningful without a scheme that defines what each point represents.

## 2.5 Prediction, draft and verified data

MorphoLabel distinguishes unfinished or machine-generated states from **human-verified** states.

A useful rule is:

**AI prediction = proposal**

**Human verification = accepted scientific annotation**

The software protects verified human annotations from routine batch prediction so that completed work is not silently replaced.

## 2.6 Annotation scheme

A scheme defines what is being annotated.

For Landmarks it contains landmark definitions and groups.

For X-rays it contains:

- repeated structures to mark and count;
- anatomical reference marks;
- biological traits calculated from those marks;
- rules relating the marks to the traits.

## 2.7 Model

A model is a trained AI component used for a particular task.

Current AI tasks include:

- Landmarks Crop;
- Landmark prediction;
- X-ray Crop/specimen detection and orientation;
- X-ray Structure annotation.

Models have identities and can be activated, compared, imported and exported.

## 2.8 Queue

A **queue** is a finite set of images or specimens that should be processed for a particular purpose.

Examples include:

- training batches;
- AI review;
- manual review;
- repeatability;
- suspicious-result review.

Queues keep review work explicit. Closing a queue leaves saved scientific data intact.

## 2.9 Repeatability

Repeatability workflows measure how consistently a human annotator can repeat the same task.

This is different from AI accuracy.

Human repeatability is useful because even a perfect computational pipeline cannot remove ambiguity in the biological definition or in the underlying image.

## 2.10 Quality control

Quality control in MorphoLabel is designed to **flag records for review**, not to make biological decisions automatically.

An outlier is not necessarily an error. It may be a real biological observation.

---

# 3. Installation and first launch

## 3.1 Install MorphoLabel

MorphoLabel currently supports **Windows 10/11 x64**.

Download the current installer from the GitHub release page:

[MorphoLabel 1.0.0-rc.1 installer](https://github.com/olegartaev/MorphoLabel/releases/download/v1.0.0-rc.1/MorphoLabel-1.0.0-rc.1-Setup-x64.exe)

Normal users do not need to install Python, Git or AI libraries manually.

## 3.2 First launch

On first launch MorphoLabel may offer to install AI support.

Before starting the download, the setup window lists the components. AI support uses a managed runtime shared by the production modules.

You have two valid choices:

- **Install AI support** — use training and prediction.
- **Continue without AI** — use MorphoLabel manually and install AI later from **Menu → AI support → Set up AI support…**.

The AI components are several GB. The installer for the main application is much smaller because the large AI runtime is managed separately.

## 3.3 Hardware qualification

During AI setup MorphoLabel checks the available hardware, including CPU, GPU, VRAM and CUDA support, and verifies that the AI environment can perform the required work.

A compatible GPU can substantially improve training and prediction speed. The application also supports CPU fallback.

You can inspect the detected status later with:

**Menu → AI support → Hardware status…**

## 3.4 Privacy

AI setup and annotation are local operations. The AI setup process does not upload research images or project data.

---

# 4. General interface logic

MorphoLabel is organized as a module hub followed by a small number of workflow stages.

## 4.1 Module hub

The start screen provides access to:

- **Landmarks & Measurements**
- **X-ray Traits**

Each module keeps its own scientific project state and models, while both can use the shared AI runtime.

## 4.2 Project stage

The Project stage is where you define the scientific context:

- project location;
- source images;
- annotation or trait scheme;
- measurement definitions where relevant;
- active models;
- image-preparation choices.

Set these correctly before large-scale annotation.

## 4.3 Image or specimen list

The left list is not just navigation. It communicates project state.

Depending on the module and stage, rows indicate states such as:

- not started;
- draft;
- pending review;
- verified;
- excluded.

Excluded items remain recoverable. Exclusion does not delete their scientific history.

## 4.4 Main image area

The main area is where the current image or specimen is edited.

Typical interactions include:

- zoom and pan;
- placing points;
- dragging existing points;
- deleting or clearing annotations;
- applying or verifying the current state.

## 4.5 Workflow cards

The lower workflow area groups actions by scientific sequence rather than by software implementation.

The common pattern is:

1. repeatability or training data;
2. train model;
3. predict;
4. review;
5. quality control and export.

You do not need to use AI to use the program.

---

# 5. Landmarks & Measurements: complete workflow

The Landmarks module is intended for anatomical landmark coordinates and distances derived from them.

## 5.1 Create a project

Open **Landmarks & Measurements** and choose **New Project…**.

Select the project destination and the folder containing source photographs, or open an existing project if you are continuing work.

MorphoLabel indexes the source images but normal project operations do not edit them.

If the source folder later moves, reconnect it with **Change folder…**.

Use **Rescan for images** when new source images have been added. Existing project work is preserved.

## 5.2 Define the landmark scheme

A landmark scheme tells MorphoLabel what every point means.

The Project page shows the active landmark scheme and the number of landmarks.

Use **Create scheme…** or **Edit scheme…** to define the landmark set.

For a scientifically useful scheme:

- each landmark should have a reproducible anatomical definition;
- homologous points should have the same identity across specimens;
- ambiguous landmarks should be avoided or documented;
- short abbreviations should be stable because they may also be used in measurement definitions.

If a landmark cannot be observed on a particular image, use **Mark missing** rather than inventing a position.

## 5.3 Decide whether to use Crop

Under **Image preparation**, choose:

- **Use Crop** — standardize specimens before placing landmarks;
- **Skip Crop** — annotate directly on the source images.

Use Crop when specimen framing or orientation varies enough to make downstream annotation harder or less consistent.

Skip it when the images are already standardized and an extra preparation step adds no useful information.

## 5.4 Crop manually

When Crop is enabled, open the Crop stage.

The current Crop can be moved, resized and rotated.

Important controls include:

- **Apply crop** — save the current reversible Crop and remain on the image;
- **Confirm & Next** — when working inside a batch, save and continue;
- **Review AI** — inspect pending AI Crop proposals;
- **Review manual** — re-review manually created Crops;
- **Accept all AI** — accept all pending AI Crop proposals exactly as predicted.

For scientific projects, reviewing AI Crops individually is the safer default than accepting them without inspection.

## 5.5 Optional Crop AI workflow

The Crop workflow is:

### A. Create training examples

Use **Start first batch**.

The current interface recommends approximately **20–30 images** for a Crop training batch. Correct and confirm them by hand.

### B. Train

The **Ready** counter reports the human-confirmed examples available for training.

Choose the training parent:

- **Bootstrap / first model** for the first model;
- or an existing model as the recorded lineage parent for a later retraining step.

Press **Train**.

### C. Predict

Choose the active model and use:

- **Predict next batch**
- **Predict all**

Only eligible uncropped images are targeted. Pending proposals are kept as review states rather than repeatedly recalculated.

### D. Review

Open **Review AI** and correct proposed Crops where necessary.

Confirmed examples become part of the human reference data.

## 5.6 Place landmarks manually

Open the Landmarks stage.

Select a landmark and place it on the current specimen.

Useful controls include:

- **Mark missing** — deliberately record a landmark as unavailable;
- **Delete** — remove the selected point so it can be placed again;
- **Clear all…** — remove editable landmarks from the current image;
- **Verify image** — accept the completed landmark set after human review;
- **Display…** — adjust marker colours, size and style.

Do not verify an image until all required landmarks are either placed or explicitly marked missing.

## 5.7 Human Repeatability

Before scaling up annotation, use **Human Repeatability…** when the project requires a quantified estimate of placement consistency.

MorphoLabel creates two independent annotation passes on the same control images.

The current interface recommends a default sample of **10 eligible images** when available.

The purpose is to estimate how much landmark position changes when the human repeats the task.

This is useful for:

- identifying poorly defined landmarks;
- estimating operator error;
- deciding whether the image quality is sufficient;
- separating annotation noise from biological variation.

Repeatability results should be interpreted in the context of the scientific question and image scale.

## 5.8 Create Landmark AI training data

The **Training data** card creates or continues a persistent training batch.

The first verified batch establishes the initial human training set. Later batches can add improvement examples.

Training examples should cover the real variation that the model will encounter, including:

- different specimen sizes;
- orientation variation;
- imaging variation;
- difficult but valid examples;
- biological variation.

A large number of nearly identical easy examples is usually less informative than a smaller but representative training set.

## 5.9 Train a Landmark model

The **Train model** card uses the human-confirmed examples.

For the first model choose **Bootstrap / first model**.

For later training you can select a saved model as the lineage parent.

Press **Train**.

Saved models remain available under **Models…**.

## 5.10 Predict landmarks

In **Predict & review**, choose the active model.

Available actions include:

- **Predict current** — apply the active model only to the current eligible image;
- **Predict next batch** — predict the next eligible group;
- **Predict all** — predict all eligible images.

Human-verified images are protected from these routine prediction actions.

## 5.11 Review AI predictions

Use **Review AI** before verification.

The review workflow prioritizes complete, unverified AI predictions and can rank higher-risk cases first.

For each image:

1. inspect all landmarks;
2. correct misplaced points;
3. mark truly missing points as missing;
4. verify the image.

Do not use apparent model confidence as a replacement for anatomical review.

## 5.12 Final data QC

**Final data QC** is intentionally separate from pre-verification AI review.

It examines already verified data for patterns that may deserve another look, including landmark-distance, within-group measurement and shape-based checks.

A QC flag means “inspect this case”, not “delete this observation”.

If a flagged specimen is biologically real and the annotation is correct, keep it.

## 5.13 Define measurements

The Measurements stage converts landmark positions into named distances.

Open **Measurement definitions…**.

For each measurement:

- define a short code or name;
- choose the two landmarks;
- keep the definition biologically consistent across specimens.

Measurement definitions can be imported and exported as portable definitions.

## 5.14 Calibrate samples

Pixel distance becomes a physical distance only after calibration.

Use **Calibrate samples** and supply a known reference distance for each sample where physical units are required.

Do not interpret uncalibrated pixel measurements as millimetres.

## 5.15 Export landmark data

The Export stage can save landmark coordinates as:

- **TPS**
- **CSV wide**
- **CSV long**
- **MorphoJ-compatible row/column text**

You can export all landmarks or selected landmark groups.

Choose the format based on the downstream software rather than on appearance.

## 5.16 Export measurements

Measurements can be exported as:

- CSV;
- tab-delimited text.

The export contains the active measurement definitions and calculated values for eligible images.

---

# 6. X-ray Traits: complete workflow

The X-ray module is designed for radiographs in which one image may contain multiple specimens and the scientific output is a set of counts, positions, distances, angles or derived traits.

## 6.1 Create an X-ray project

Open **X-ray Traits** and choose **New Project…**.

During project creation, MorphoLabel asks for the standard orientation.

Define:

- which side the head faces;
- which side the ventral side faces.

The orientation preview uses **blue for the head** and **orange for the ventral side**.

A consistent standard orientation makes later review and model training more reliable.

## 6.2 Source X-rays and self-contained projects

The Project page lists the indexed source radiographs.

An X-ray project can use external source files or be made self-contained with:

**Make self-contained…**

This copies the source X-rays into the project so the project can open without the original folder.

Use **Clear reproducible cache** to remove disposable derived files without deleting source X-rays, scientific annotations or final trained models.

## 6.3 Define the trait scheme before mass annotation

Open **Traits…**.

The trait editor separates three ideas.

### A. Repeated structures

These are objects that may be marked multiple times, for example vertebrae.

### B. Reference marks

These define anatomical boundaries or positions.

A reference can be:

- an independent anatomical mark;
- or a role assigned to one element in a repeated series.

### C. Biological traits

Traits are the final values calculated from annotations.

Supported trait methods are:

- **Count objects**
- **Count up to a reference**
- **Count between two references**
- **Position in a series**
- **Presence / absence**
- **Measure distance**
- **Measure angle**
- **Calculated from other traits**

The trait scheme therefore separates raw image annotation from the biological variable that will be exported.

This is useful when several traits are derived from the same set of annotated structures.

## 6.4 Counting rules

For boundary-based counts, the trait editor supports rules such as:

- **Before** — the boundary element is excluded;
- **Through** — the boundary element is included;
- **From** — counting starts at the boundary and includes it.

Use the preview to confirm that the rule corresponds to the biological definition before annotating a large dataset.

## 6.5 Apply the trait scheme to the project

Edits in the Traits dialog are initially a draft.

**Save trait** saves the selected trait definition inside that draft.

**Use these traits for project** applies the complete trait set to the current project.

This separation helps prevent a partially edited trait rule from silently changing ongoing work.

## 6.6 Crop specimens from X-ray plates

Open **Crops**.

A plate may contain several specimens.

To create a specimen Crop:

1. drag on empty image space to create a frame;
2. drag the frame to move it;
3. drag a corner to resize it;
4. use the outer rotation handle to rotate it;
5. check the specimen identity;
6. check head and ventral orientation.

Useful controls include:

- **Delete** — remove only the selected Crop;
- **Clear all…** — remove all Crops from the current plate;
- **Flip ↔** — reverse head direction;
- **Flip ↕** — reverse ventral direction;
- **Apply crops** — confirm the current plate and stay on it;
- **Confirm & Next** — confirm and advance through a queue.

The source radiograph remains unchanged.

## 6.7 Specimen identity

Each Crop corresponds to a specimen identity.

The selected specimen ID can be edited. The current interface also supports **F2** for editing the selected specimen ID.

Make specimen identities stable before annotation because they link Crop, Structures and exported traits.

## 6.8 Excluding a plate

The X-ray Crop list has **Exclude / Restore**.

Plate exclusion skips the plate in active workflows without deleting its Crops or history.

Use exclusion for images that should not participate in the current analysis, not as a substitute for deleting errors.

## 6.9 Optional X-ray Crop AI

The X-ray Crop model can learn to find specimens and their orientation.

The workflow is:

1. **Start first batch** — the current interface recommends **6–10 different plates**;
2. correct and confirm Crops and directions;
3. **Train**;
4. choose the active model;
5. **Predict current**, **Predict next batch** or **Predict all**;
6. **Review AI**;
7. correct and confirm the proposals.

Human-reviewed plates are protected from routine prediction overwrites.

## 6.10 Annotate X-ray Structures

Open **Structures**.

Choose a marker type and click each anatomical structure.

For repeated structures, MorphoLabel numbers points in spatial series order.

You can:

- place markers;
- drag a marker to correct it;
- delete an individual marker;
- clear one marker category;
- clear all markers;
- adjust display colours, symbols and sizes.

The marker dock shows the current count for each structure type.

When numeric shortcuts are available, marker types can be selected with their displayed number keys.

## 6.11 Reference roles and counting boundaries

Some reference points are biologically part of a repeated series.

For example, a particular vertebra can simultaneously be:

- one element of the vertebral series;
- the anatomical boundary between two count regions.

In these cases, right-click the appropriate repeated-series marker and assign its compatible reference role.

This avoids creating two different points for the same anatomical object.

Independent references are placed as their own marker type.

## 6.12 Structure visibility states

Each marker type has a visibility/status control.

Current states are:

- **Complete** — all visible instances have been marked;
- **Partial** — only some visible instances can be reliably marked;
- **Not visible** — the structure cannot be judged on this X-ray;
- **Absent** — the biological structure is truly absent.

Use these states carefully.

**Not visible** and **Absent** are scientifically different. The first describes the information in the image; the second describes the biological state.

If you change a structure to a state incompatible with existing markers, MorphoLabel asks before clearing those markers.

## 6.13 Verify a specimen

Use **Verify specimen** after checking the marker set.

Inside an annotation batch, use **Verify & Next** to verify and advance.

Verification is what turns the current marker set into accepted human-reviewed data.

## 6.14 Excluding one specimen

The Structures list has **Exclude / Restore** at specimen level.

This is different from excluding the entire X-ray plate.

Specimen exclusion:

- removes that specimen from active Structure, AI and export workflows;
- keeps the Crop, annotations and history;
- can be reversed later.

Use specimen exclusion when a particular individual is unsuitable but other individuals on the same plate are valid.

## 6.15 Human Repeatability for Structures

The Structure module can create two independent annotation passes for the same specimens.

Repeatability annotations are kept separate from the main training truth.

This is important: a repeatability exercise should measure the human process, not inflate the AI training set with duplicated annotations of the same specimen.

## 6.16 Train Structure AI

Create a verified main-annotation training batch.

The **Ready** counter reports the number of human-verified main annotations available.

The current interface uses **ImageNet ResNet18** as the initial starting point; later saved Structure models can be selected as training lineage parents.

Press **Train**.

## 6.17 Predict Structures

Choose the active Structure model, then use:

- **Predict current**
- **Predict next batch**
- **Predict all**

AI produces an editable draft.

Verified annotations are kept protected by the workflow rules.

## 6.18 Review Structure AI

Use **Review AI** to inspect saved AI drafts.

For each specimen:

1. check that every required structure is marked;
2. correct marker positions;
3. correct counts;
4. check reference roles;
5. check visibility states;
6. verify the specimen.

## 6.19 Check calculated results

Use **Check results…**.

MorphoLabel examines calculated trait values and creates a review queue for suspicious cases.

The review banner identifies the current case and why it was flagged.

A flagged value may be biologically genuine. Inspect the image and annotation rather than automatically normalizing or deleting the value.

## 6.20 Export X-ray traits

Open **Export**.

Choose:

- **All**
- **Verified only**

For a final scientific dataset, **Verified only** is generally the safer choice unless unfinished rows are intentionally required for internal checking.

The export is a CSV table containing specimen identity and the active trait columns.

---

# 7. AI models and model management

## 7.1 AI is project assistance, not ground truth

MorphoLabel treats the model as an annotation assistant.

The preferred cycle is:

1. human examples;
2. train;
3. predict;
4. review;
5. correct;
6. verify;
7. add informative corrections to later training.

This is a human-in-the-loop workflow.

## 7.2 Training data quality matters more than raw quantity

Training examples should represent the real range of the project.

Avoid a training set composed only of easy, nearly identical images.

Include:

- common morphology;
- unusual but valid morphology;
- imaging variation;
- difficult orientations;
- different specimen sizes;
- representative quality variation.

Do not intentionally include incorrect annotations merely to increase sample size.

## 7.3 Model lineage

When a model is trained, MorphoLabel records the selected parent or starting model.

This helps distinguish:

- a first model;
- a later improvement;
- a model imported from another compatible project.

## 7.4 Active model

The active model is the model used by prediction controls.

Always check the active model before a large **Predict all** operation.

## 7.5 Import and export

Models can be moved between projects or computers using portable model ZIP packages.

The package contains model weights and inference settings. Source research images are not included.

Only reuse a model when the target project is biologically and structurally compatible with the model’s annotation scheme.

## 7.6 When to retrain

Retraining is useful when review reveals systematic errors, for example:

- a particular body orientation;
- a new imaging setup;
- a size class absent from the first batch;
- a difficult anatomical region;
- a consistent marker-placement bias.

Randomly adding many easy examples may improve little.

---

# 8. Repeatability and quality control

## 8.1 Human repeatability answers a different question from AI accuracy

AI accuracy asks:

**How close is the model to the human reference?**

Human repeatability asks:

**How consistent is the human reference itself?**

Both matter.

If the same expert places a landmark very differently on repeated attempts, that landmark definition may not support the precision expected from the model.

## 8.2 Use repeatability early

A good time to run repeatability is before the full dataset has been annotated.

Early repeatability can reveal:

- unclear landmark definitions;
- poor image standardization;
- ambiguous boundaries;
- a need to revise the scheme.

Fixing those problems after thousands of annotations is much more expensive.

## 8.3 Quality control is a review tool

MorphoLabel quality control should not be treated as an automatic outlier-removal procedure.

A suspicious result can arise from:

- annotation error;
- image defect;
- wrong specimen identity;
- wrong Crop;
- unusual orientation;
- real biological variation.

The program helps find the case. The researcher decides what it means.

---

# 9. Working efficiently with large datasets

For large projects, the order of operations matters.

## Recommended pattern

1. Define the scheme carefully.
2. Test it on a small, diverse set.
3. Run human repeatability.
4. Fix ambiguous definitions.
5. Create a first verified training batch.
6. Train a first model.
7. Predict a moderate batch.
8. Review every prediction.
9. Identify systematic model failures.
10. Add informative corrected cases.
11. Retrain.
12. Increase batch size only after the workflow is stable.
13. Run final quality control.
14. Export verified data.

## Why not use Predict all immediately?

A model that is wrong in a systematic way can create a large amount of review work.

A moderate pilot batch reveals whether the model has learned the intended anatomy before it is applied to the whole collection.

## Use queues rather than memory

If MorphoLabel creates a review queue, work through it or close it deliberately.

Do not rely on remembering which images were “probably checked”.

Persistent review state is one of the main advantages of a project-based workflow.

## Exclude rather than delete scientific exceptions

If an image or specimen should not be analyzed, exclusion is usually preferable because it retains the record and can be reversed.

Deletion should be reserved for cases where the object itself was created by mistake and has no scientific reason to remain.

---

# 10. Data safety, provenance and backup

## 10.1 What MorphoLabel preserves

Depending on the module, the project can preserve:

- source paths and source identity information;
- Crop transformations;
- orientation;
- annotations;
- missing or visibility states;
- verification state;
- model identity;
- prediction provenance;
- repeatability sessions;
- quality-control state;
- exclusions;
- trait or measurement definitions;
- calibration;
- export-relevant workflow metadata.

## 10.2 What should be backed up

Back up:

1. the complete MorphoLabel project folder;
2. any source-image folders referenced externally.

For X-ray work, **Make self-contained…** can simplify archiving by copying the source radiographs into the project.

## 10.3 Do not use the GitHub repository as research-data storage

The public source-code repository is not the place for:

- project databases;
- unpublished images;
- private specimen records;
- credentials;
- generated diagnostic reports containing local environment information.

Keep research projects in your own selected storage and backup system.

## 10.4 Reproducible cache

Some derived files can be recreated.

The X-ray command **Clear reproducible cache** removes disposable cached material while keeping source X-rays, scientific data and final models.

---

# 11. Export and downstream analysis

MorphoLabel exports data; it does not replace statistical analysis software.

## 11.1 Landmark coordinates

Available formats include TPS, CSV and MorphoJ-compatible text.

Typical downstream uses include:

- geometric morphometrics;
- Procrustes-based analyses;
- shape visualization;
- multivariate statistics.

## 11.2 Linear measurements

Exported measurement tables can be analyzed in R, Python, spreadsheets or statistical packages.

Always verify whether the measurements are calibrated to physical units before interpreting scale.

## 11.3 X-ray traits

The X-ray CSV contains the calculated trait table.

Use **Verified only** when preparing the analysis dataset after human review.

## 11.4 Keep the project after publication

Do not treat the export as the only valuable output.

The project contains the provenance needed to revisit an annotation, inspect a model prediction or reproduce the export.

---

# 12. Troubleshooting and support

## 12.1 AI was skipped on first launch

Open:

**Menu → AI support → Set up AI support…**

You can install it later without recreating the project.

## 12.2 AI setup failed

Retry the guided setup.

Partial downloads are kept locally and can resume.

If the problem repeats, create a diagnostic report.

## 12.3 Create a diagnostic report

Open:

**Menu → Support → Create diagnostic report…**

MorphoLabel creates a diagnostic ZIP and provides controls to open its folder or copy its path.

The diagnostic ZIP is designed not to include:

- research photographs;
- the project SQLite database.

Attach the ZIP when reporting a reproducible technical problem.

## 12.4 An image should not be analyzed

Use **Exclude** rather than deleting scientific work.

Restore it later if needed.

In X-ray projects, remember that there are two exclusion levels:

- plate exclusion in Crops;
- individual specimen exclusion in Structures.

## 12.5 AI prediction looks wrong

Do not verify it.

Correct the annotation manually, then verify the corrected state.

If the same failure repeats across many images, add representative corrected cases to the training data and retrain.

## 12.6 A quality-control result is biologically plausible

Keep it if the source image and annotation are correct.

Quality control is a review trigger, not a rule that the specimen must be removed.

## 12.7 The source folder moved

For the Landmarks module, use the project’s source-folder relinking controls rather than rebuilding the project.

For X-ray projects, consider making the project self-contained before moving it between computers.

## 12.8 Need to move a trained model

Use the model import/export controls rather than copying internal runtime folders manually.

---

# 13. Scientific limitations and good practice

MorphoLabel can make annotation faster and more traceable, but it cannot solve a poorly defined biological problem.

## 13.1 The software cannot define homology for you

A landmark is useful only if the same biological structure is identified consistently across specimens.

A model can reproduce a definition. It cannot establish whether that definition is biologically homologous.

## 13.2 AI quality is bounded by the reference annotations

If training annotations are inconsistent, the model will learn that inconsistency.

For this reason, repeatability and review are part of validating the measurement process in high-precision studies.

## 13.3 Image quality sets an upper limit

If a structure cannot be resolved in the source image, the correct scientific state may be **missing**, **partial** or **not visible**, not a guessed coordinate or marker.

## 13.4 Avoid silent scheme drift

Do not change landmark or trait definitions halfway through a project without documenting and validating the change.

A definition that changes meaning produces a dataset that may look numerically complete but is biologically inconsistent.

## 13.5 Preserve the final project and software version

For reproducibility, retain:

- the project;
- the source images;
- the exported data;
- the active scheme;
- the trained model when AI contributed;
- the MorphoLabel version used.

---

## Support and citation

Repository: https://github.com/olegartaev/MorphoLabel

Questions: **morpholabel@olegartaev.com**

Citation metadata: [CITATION.cff](../CITATION.cff)

License: [Apache License 2.0](../LICENSE)
