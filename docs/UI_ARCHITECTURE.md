# Production UI architecture

## Startup and rollback

`START_APP.cmd` starts `app.ui.shell.ProductionShell` directly.  The shell supports `project=None`: Project is active and contains **New Project...** and **Open Project...**.  Creating or opening a project attaches it to that same Tk window; no second main application is launched.

The desktop source launcher is `START_APP.vbs` (also invoked by `START_APP.cmd`). It starts the production shell through `RUN_CANONICAL.cmd` with a hidden console, logs startup output and reports failures in a dialog. `RUN_CANONICAL.cmd` remains the visible developer diagnostics route. All routes use the same portable `Project` storage and never migrate scientific data merely to open a UI.

## Shell and shared state

`app/ui/shell.py` owns one Tk window and one `UIContext` (`app/ui/context.py`).  It renders the thin stage row, compact work-status row, image navigation, menus and delayed tooltips. `UIContext.refresh()` caches the catalog. The initial `counts()` cache holds a per-image classification; a single annotation edit calls `update_image_counts()` to recompute and delta-adjust only that image, so warm switches and normal landmark edits do not rescan the catalog. With a project open, Crop/Landmarks/Measurements share a horizontal `ttk.Panedwindow`: `PhotoListPanel` is on the persisted, clamped `workspace_sidebar_sash` left pane, while status and the image workspace expand on the right and its workflow strip is a fixed bottom row.

`app/ui/photo_list_panel.py` is the shared list controller.  It wraps the established `app.photo_list.PhotoListCanvas` and deliberately imports the proven ReadyEditorV15 `photo_search_cache` / `filtered_photo_indices` behavior.  This retains virtual rows, scroll bar, wheel and keyboard navigation, selection visibility, status dots, crop marker, review warning, exclusion appearance and catalog-only filename/locality filtering. User row selection updates only the active canvas/status; it deliberately does not rebuild the panel or invoke `see()`, so the exact scroll position stays stable.

`section_registry.py` registers workflow stages.  Adding a future module requires one section view, one registry record and one `ProductionShell` mapping entry; it does not require changing crop, landmark, calibration or storage algorithms.

## Section views

- `project_section.py`: same-window New/Open, source root/relinking, compact scrollable sample table, active project schema and workflow preferences.
- `crop_section.py` with `crop_canvas.py`: main-workspace reversible crop editing and the existing crop training/prediction/review services.
- `landmarks_section.py` with `landmark_canvas.py`: main-workspace landmark editing.  It uses a saved standardized PNG when Crop is used; with Skip crop it safely prepares/displays the established full developed image as identity coordinates, never fabricating a crop.
- `measurements_section.py`: existing CalibrationWorkflow and MeasurementsWindow plus a read-only main-workspace preview that draws saved landmark abbreviations and active measurement connections. A skipped crop uses the developed image with a non-persisted identity transform for measurement calculation; it never creates a synthetic crop record.
- `export_section.py`: project-level landmark/measurement exporter controls without a specimen canvas. Export grouping uses the active schema category, then the real role as a backward-compatible fallback, consistently across TPS/CSV/MorphoJ formats.

## Scientific boundaries

Section views render controls and invoke existing services: `Project`, `crop_training_batch`, `crop_training`, `crop_auto`, `landmark_training_workflow`, `landmark_ai_workflow`, `CalibrationWorkflow`, `MeasurementsWindow`, `results_export`, `measurements`, `ai_hardware` and `ai_package`.  `app/calibration_workflow.py` resolves its image through the active `Project.cache_root`, using the existing developed-cache pipeline within `scoped_project`; it does not use a machine-global cache path.

The storage database, original files, coordinate transforms, provenance, Human Baseline/QC, calibration and model packages remain the authority outside `app/ui`.

## Verification

`tests/test_production_ui_acceptance.py` creates disposable projects and checks startup, stage/tab state, Crop visibility, PhotoListCanvas, fixed workflow geometry, schema/project storage, export services and source hashes.  GUI automation/screenshots are supplementary evidence; focused tests never open or modify user projects.
## Repair QA details

`app/ui/crop_canvas.py` caches its raster image and redraws only vector overlay geometry while dragging. CalibrationWorkflow keeps one instance across locality/image navigation and now has a maximize/restore control; its active-project cache resolution remains isolated from global cache state. `tests/test_production_ui_acceptance.py` includes deterministic warm-switch, 1,303-row scroll preservation, Skip-crop identity measurement and schema-group export regressions.

## Latest production repair

app/ui/preferences.py stores only the last successfully opened project in the user profile. ProjectSection owns its persisted Samples sash. LandmarkSidebar combines the legacy virtual photo list and reusable status landmark table; LandmarkCanvasController owns only asynchronous prepared-image presentation and calls Project storage for scientific edits. MeasurementPreview is read-only and selects an eligible image. Export services accept an optional direct destination, so the UI can use Save As without write-then-copy behavior.

## Responsive operator details

pp/ui/preferences.py keeps only a validated, resolved user-level last-project path and records read/write/open failures in diagnostics. ProductionShell defers selected-image work until Tk is idle; the virtual PhotoListCanvas therefore paints selection immediately and never moves its scroll position for a click. The scientific sidebar is a persisted horizontal PanedWindow.

LandmarkCanvasController is the reusable legacy-style operator component: tokenized prepared-image loading, cached raster, `EditorState` current-landmark selection, canonical Project state and vector-only mouse dragging. Existing points win the 10-pixel hit-test; blank clicks place only the first unresolved landmark. Motion changes only existing oval/label canvas coordinates; release makes one canonical save then one authoritative refresh. LandmarkSidebar is the paired legacy table/list controller and clamps its persisted vertical sash so neither list can be hidden.

## Schema and active Crop batches

`Project` owns the canonical landmark schema. `abbr` is the persistent scientific identity; `id` is regenerated from CSV row order solely for display. `Project.open()` isolates a malformed schema as `schema_error`, allowing Project and Crop to remain usable until the project-local `SchemaEditor` repairs it. The editor is the only writer of canonical clean `id,abbr,name,role` CSV.

`CropSection` owns active crop-batch navigation. Its persisted `crop_active_batch` UI state records batch id/type, ordered ids, prepared ids, completion ids, and position. `CropCanvasController` loads prepared batch images directly and does not rerun preparation per image.
