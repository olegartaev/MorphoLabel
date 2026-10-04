# Release UI review

The review branch is `design/release-ui`, based on
`feature/xray-traits-foundation` at
`60fb7dbee4068d0a1f87045df6a617205d8c1f79`. No merge into the feature branch or
main is part of this change. Approval is required after GUI review.

## Preview

On Windows, run `START_DESIGN_PREVIEW.cmd`. Choose Landmarks or X-ray traits.
It opens the actual production UI with small, artificial projects in the
git-ignored `.design-preview` directory. This process isolates preferences,
diagnostics and last-project history. It does not open or copy research data.
The images and model seed are explicitly synthetic. No AI training/download
is needed. Edits made during preview are retained only in these demo projects.

To open a specific module directly:

```
START_DESIGN_PREVIEW.cmd --module landmarks
START_DESIGN_PREVIEW.cmd --module xray
```

Normal launchers and scientific workflows are unchanged. Real-project testing
should follow only after the demo layout is accepted, using a backup.

## Presentation changes

- On Windows, standard ttk Windows themes provide the ordinary desktop control chrome; custom blue panel/button skinning is avoided. Semantic warning/review states remain distinct.
- Shared spacing, typography, active-stage appearance and primary buttons.
- Workflow cards are vertically compact; commands with different roles are grouped inside each stage instead of being scattered across the card.
- All stages in one wide Workflow row use the same height, set by the tallest compact stage. Stages are separated by whitespace rather than vertical divider bars; Crop, Landmarks and X-ray use the same card geometry.
- Batch prediction controls start with `Next batch`, use the shared `Predict next batch` action, and keep unresolved/review/verified counters in the common context/status row rather than inside one workflow card.
- Model provenance is rendered over the working image in the established yellow Landmarks style, using persisted model IDs and event/prediction timestamps only.
- X-ray context rows use bold field names (`Sample`, `Plate`, `Crop`, `Specimen №`) with normal-weight values; the vertical orientation control uses the same orange as the ventral marker.
- Core Crop keeps the source image visually fixed while its editable crop frame rotates; the persisted rotation/crop transform is unchanged and regression-tested against `Transform.original_to_standardized`.
- Crop/Structures side lists open wide enough for readable labels while remaining capped near 29% of the workspace, and model-list dialogs expand to expose their normal columns when screen width allows.
- The current-project block is visually distinct from project settings and uses a concise Open action.
- The Traits editor opens large enough to expose both biological-definition steps when possible, otherwise maximizes, and uses explicit anatomical/counting language for reference marks.
- One original drawn icon family. Batch/prediction actions use specimen-card, stack and review metaphors rather than generic lines/dots. X-ray visibility uses larger anatomical eye/occlusion icons; `Not visible` is an eye with a slash, while `Absent` is an empty anatomical slot, so the two states do not share a silhouette.
- Existing scientific annotation symbols on the image remain unchanged; only toolbar/status icon presentation is enlarged.
- Common image context, actions, image canvas and workflow organization.
- Wide windows show workflow cards together. Compact windows show stage tabs;
  controls retain their original commands and variables. Workflow can collapse.
- Queue navigation is one additive yellow strip immediately above the working image: Previous, confirmation/next, Close queue. Result inspection retains its separate Next without confirmation. Saved queues show Continue without pretending that the current item is active.
- The top bar exposes one `Queues` browser immediately left of `Menu`; it lists persisted annotation/review queues and opens the saved position. Its label does not cache a numeric count, avoiding stale `Queues (n)` badges after a queue is closed.
- Context rows use one vocabulary: `Sample` plus `Image` for core photographs, and `Sample | Plate | Crop/Specimen №` for X-ray workspaces. Keys are bold; values are normal weight and receive explicit width so long sample names remain readable.
- Crop, Landmarks, X-ray Crop and Structure training use the same `Active | From` pattern. The active compatible model is the initial `From` selection. X-ray selectors choose a real saved parent or pretrained baseline; core Crop records the selected lineage parent while retraining its closed-form model from the full verified Crop dataset.
- `Close queue` removes that queue's navigation state everywhere while preserving scientific annotations, prediction provenance, model history and repeatability records. Landmark training membership remains scientific state and is not deleted; a separate persisted closed-navigation flag prevents it from reappearing until the workflow is explicitly continued. X-ray annotation-batch Close clears `xray_structure_active_batch` and returns the Structures list to the normal main pass.
- X-ray prediction captions read the actual model seed/detection event time.
  Human edits and verification do not replace the original prediction time.
- About separates core credit from per-module authors. Credits are presentation
  metadata in `app/ui/module_credits.py`; unknown extension authors are not guessed.
- Specimen workflow number and ordinal within a plate have distinct meanings: `Specimen №` always means the specimen ordinal on the current plate, while the export table's first `#` column is the project-wide row/workflow index. The current specimen selection is persisted across Crop → Structures → Export, and selecting an Export row updates the context header without moving the list viewport.

Model training/inference implementations, schemas, coordinates, visibility
states, scientific marker rendering, QC algorithms, result calculations and
export data formats are unchanged. Project storage and database schemas are
unchanged. Confirmation, exclusion, repeatability and persistence callbacks
retain their existing validation/protection rules.

## Review checklist

Review at normal and compact widths and the Windows display scaling you use:

1. Project → Crop → Landmarks/Structures → Measurements/Export use the same
   visual language; current image and active stage are clear.
2. All workflow tabs are reachable; collapse increases image space.
3. Crops: deletion, both flips, Apply and batch confirmation remain distinct.
4. Structures: select marker type, place/move/delete marks, change visibility,
   distinguish Complete / Partial / Not visible / Absent at a glance, assign a reference role, Verify, and inspect model/time caption.
5. Previous does not confirm. Verify & Next rejects incomplete annotations.
   Close queue removes navigation and keeps annotations.
6. Traits opens with both definition steps reachable; the reference-mark wording is biologically clear and no essential controls are clipped.
7. Model-list windows show all normal columns when the display is wide enough; Crop/Structures side lists are readable without taking over the image canvas.
8. About identifies core and module authors separately.

Automated presentation tests are in `tests/test_release_ui_presentation.py`.
Tk layout tests require a display and run against real project APIs. Linux
screenshots are useful for review, but Windows GUI approval is still pending.

## Integration after approval

Keep this branch as the review checkpoint. Once the design is approved, merge
its UI commit into the current X-ray feature branch and run the focused checks
against the resulting exact HEAD. Do not merge this branch into main: its base
contains the experimental X-ray module. Any later stable-core integration must
be scoped to the approved core UI files and tested separately.
