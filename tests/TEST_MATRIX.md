# Current regression coverage

| Area | Regression files |
|---|---|
| Project/storage | `test_project_acceptance.py`, `test_restored_regressions.py` |
| Crop | `test_crop_auto_workflow.py`, `test_crop_training.py`, `test_restored_regressions.py` |
| Landmark state | `test_annotation_drafts.py`, `test_restored_regressions.py` |
| Checked/Train ready | `test_operator_qc.py`, `test_restored_regressions.py` |
| Exclude/Restore | `test_operator_qc.py`, `test_restored_regressions.py` |
| Schema compatibility | `test_schema_reload_and_role_display.py`, `test_restored_regressions.py` |
| Dataset/model lineage | `test_landmark_ai_stage_lineage.py`, `test_restored_regressions.py` |
| AI prediction history | `test_landmark_ai_service.py`, `test_restored_regressions.py` |
| QC | `test_operator_qc.py`, `test_production_workflow_gaps.py`, `test_restored_regressions.py` |
| Human repeatability | `test_operator_qc.py`, `test_repeatability_review_ui_regression.py` |
| Measurements/calibration | `test_measurements.py`, `test_restored_regressions.py` |
| Export | `test_export_categories.py`, `test_results_export.py`, `test_restored_regressions.py` |
| Production UI | `test_morpholabel_ui_contract.py` |
| Launcher/provenance | `test_canonical_execution.py`, `test_morpholabel_ui_contract.py` |

This matrix describes current coverage ownership. It is intentionally not a
test-count contract.
