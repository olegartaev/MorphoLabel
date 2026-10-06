# RC1 root-cause repair validation

Start SHA: `fc8c885e9505360b12ace235dc4c16e9ca8e78b5`.

This is the repair and regression phase following diagnostic commit
`92320d4a45fa37d3528a576e5335814401d0a4d4`. The application version remains
`1.0.0-rc.1`. No release, tag, or second deep qualification was performed.

| Finding | Enforced invariant | Focused minimized witness |
|---|---|---|
| ML-P0-001 | Angles use oriented crop pixel scales; persisted points and normalized distance semantics are retained. | `test_rectangular_angle_uses_oriented_pixels_through_persist_reopen_export` |
| ML-P0-002 | Base traits precede dependency resolution; multilevel derived traits are order independent, and cyclic/unresolved results are missing. | `test_derived_base_display_order_is_independent_after_reopen_and_export` |
| ML-P0-003 | Cosmetic versions retain their scientific identity, verified runs, results, training truth, repeatability state, and export. | `test_cosmetic_scheme_version_preserves_verified_runs_results_repeatability_and_export` |
| ML-P0-004 | IDs respect both registry and directories; complete staged children publish before registration and failure cleanup owns only the new child. | `test_crop_imported_v004_duplicate_imports_train_unique_child_keep_parent_hash_and_lineage` |
| ML-P1-001 | TPS/result text writes and TPS reads support UTF-8 without adding a BOM; ASCII bytes stay identical. | `test_unicode_landmark_tps_and_metadata_survive_reopen_without_bom` |
| ML-P1-002 | Malformed UI JSON returns the caller's default with a diagnostic and leaves stored UI/scientific rows intact. | `test_malformed_ui_queues_return_default_without_rewriting_scientific_or_ui_rows` |
| ML-P1-003 | MMEngine deletion flags occur only when replacing inherited train configuration. | `test_portable_base_without_train_cfg_loads_ordinary_epoch_loop` |
| ML-P2-001 | Explicit unfinished drafts block both automatic verification paths until the real finish operation clears workflow state. | `test_unfinished_complete_landmark_draft_stays_unverified_until_explicit_finish` |
| ML-P2-002 | Selector, current/batch prediction, manager status, and training-parent choices use the backend semantic compatibility predicate. | `test_legacy_v007_semantic_selector_current_batch_and_parent_eligibility_survive_reopen` |
| ML-P3-001 | Documentation checks require version, modules, installer, safety/provenance, citation, license, and release status without obsolete prose. | `test_release_documentation_public_contract_and_user_guide` |
| AI-SETUP-PRESTART | Before installation the Core remains ready, waiting components are explicit, progress is hidden, and the install action starts once. | `test_ai_setup_prestart_hides_progress_and_click_reveals_work_prevents_double_start` |

All witness tests are in `tests/test_rc1_repair_invariants.py`. Related regressions
also cover square/rotated geometry, normalized distances, dependency cycles and
cycle descendants, scientific changes, legacy verification backfill, ID gaps,
orphan directories, late publication collisions, failed registration, and
registered imported Landmark IDs.

Scientific versions retain their original saved payloads. Additive
`scientific_version_id` and `scientific_hash` metadata link new cosmetic records
to the existing scientific identity without copying or rewriting annotation
runs. The contract retains identities, model channel order, annotation types,
requiredness, relationships, all rules/dependencies, reference provenance, and
unknown extensions; it excludes only specified presentation metadata and trait
display order. A scientific change creates a separate scientific identity.
Structure model compatibility remains based on its target contract, so a trait
calculation change does not invalidate unchanged model targets.

Neighbor review found the same unsafe destination cleanup in Crop, Structure,
and Landmark imports, and missing failure cleanup in Structure training. These
now share owned staging/publication. Landmark allocation already checks registry
and artifacts; its training entry point also refuses an existing imported ID
before writing child artifacts. Orientation scratch belongs to the unique child
staging directory.

Validation:

- Python compilation: all **210** Python files under `app`, `ai_runtime`, and `tools` passed.
- New minimized and related regressions: **22 passed**.
- Focused run: **314 tests, 0 failures, 0 errors, 0 skips** across 27 subsystem modules.
- Actual MMEngine loading in the installed AI runtime: **4 tests passed**, covering both portable and inherited bases.
- Real RTMPose: export compatible model, import into a second disposable project, train one epoch, register child, activate/reopen, and export nine specimens; all three parent artifacts remained byte-identical.
- Real X-ray Crop: imported v004 plus two duplicates, detector continued training and orientation learning, unused v001 child, preserved parent lineage on reopen, exported detector/orientation package, protected parent deletion; all four parent artifacts remained byte-identical.
- Scientific compatibility: the frozen architecture oracle is unchanged; tests explicitly verify additive identity metadata before comparing every original column/export and exact reopen state.
- Protected originals: **11,350 files unchanged**, with no additions/removals; all **653 X-ray source images unchanged**, verified read-only against the qualification baseline.
- Full mandatory suite: **1,193 tests, 0 failures, 0 errors, 1 skip**, in 348.768 seconds. The unchanged accepted skip is the optional RTMPose bootstrap environment check.

Release status: **READY FOR SECOND DEEP QUALIFICATION**. This does not authorize RC2 publication; the version remains unchanged.
