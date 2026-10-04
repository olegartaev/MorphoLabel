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
- Workflow cards are vertically compact; commands with different roles are grouped with spacing and vertical separators instead of being scattered across the card.
- Workflow cards no longer stretch short stages to the height of the tallest card; each stage is capped at roughly two compact control rows in the reviewed modules.
- Model provenance is rendered over the working image in the established yellow Landmarks style, using persisted model IDs and event/prediction timestamps only.
- X-ray context rows use bold field names (`Sample`, `Plate`, `Crop`, `Specimen №`) with normal-weight values; the vertical orientation control uses the same orange as the ventral marker.
- Core Crop keeps the source image visually fixed while its editable crop frame rotates; the persisted rotation/crop transform is unchanged and regression-tested against `Transform.original_to_standardized`.
- Crop/Structures side lists open wide enough for readable labels while remaining capped near 29% of the workspace, and model-list dialogs expand to expose their normal columns when screen width allows.
- The current-project block is visually distinct from project settings and uses a concise Open action.
- The Traits editor opens large enough to expose both biological-definition steps when possible, otherwise maximizes, and uses explicit anatomical/counting language for reference marks.
- One original drawn icon family; existing scientific marker symbols remain.
- Common image context, actions, image canvas and workflow organization.
- Wide windows show workflow cards together. Compact windows show stage tabs;
  controls retain their original commands and variables. Workflow can collapse.
- Queue navigation is grouped separately: Previous, confirmation/next, Close
  queue. Result inspection retains its separate Next without confirmation.
- Closing navigation preserves annotation data. Core queue membership remains
  stored and can be reopened through its workflow action. X-ray queue closing
  uses its existing UI-state behavior; the new annotation-batch Close clears
  only `xray_structure_active_batch`.
- X-ray prediction captions read the actual model seed/detection event time.
  Human edits and verification do not replace the original prediction time.
- About separates core credit from per-module authors. Credits are presentation
  metadata in `app/ui/module_credits.py`; unknown extension authors are not guessed.
- Specimen workflow number and ordinal within a plate have distinct labels.

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
   assign a reference role, Verify, and inspect model/time caption.
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
