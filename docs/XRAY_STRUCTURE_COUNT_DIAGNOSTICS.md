# X-ray Structure AI: count-accuracy diagnostic plan

Status: code audit only, 2026-10-25. No project images, user project database, or model checkpoints were available for a direct performance experiment. Do not interpret model comparisons below as a controlled benchmark.

## Problem and available observations

The UI "Structure AI vs human" compares a model with its own saved validation membership, using human annotations from pass 1. It does **not** compare the special Human Repeatability pass 1/2.

Observed from screenshots (different validation memberships):

| Measure | v001 (N=17) | v002 (N=23) |
| --- | ---: | ---: |
| Vertebra F1 from Structure AI vs human | 0.977 | 0.966 |
| Vertebra exact-count rate | 1/17 = 5.9% | 7/23 = 30.4% |
| Vertebra count MAE | 1.353 | 1.348 |
| Vertebra count bias (AI - human) | -1.353 | -1.348 |
| First caudal role ordinal accuracy | 58.8% | 50.0% |
| Last predorsal role ordinal accuracy | 81.2% | 47.1% |
| Pre-anal pterygiophore exact-count rate | 18.8% | 37.5% |
| Correct all evaluated traits | 0/17 | 1/23 |

The change in exact-count rate cannot establish a causal model improvement, because the subsets are different. A near-identical count MAE and systematic negative bias warrant investigating missed detections, but do not prove the mechanism.

## Findings grounded in current main source

1. **Training curves are lost**: ai_runtime/xray_structure_runner.py computes epoch-level train_loss and val_loss in history but does not persist that list in its returned metrics or model.json. A plateau vs overfitting cannot be diagnosed from saved v001/v002 metadata.
2. **Validation membership is not frozen across runs**: app/xray_structure_ai.py `_split_by_plate` re-shuffles all source plate IDs (seed 42 by default), with about 20% of plates chosen for validation. Adding images can change group membership even with the same seed. Per-run train/val plate separation is enforced, but cross-run comparability is not.
3. **Parent-model contamination is not audited**: `train_structure_model` loads the parent model checkpoint, while `prepare_structure_training_dataset` generates a fresh train/val split. No evident ancestry check guarantees that the child's validation specimens or source plates have never been included in a parent's training split. This is a *risk to audit on the actual project*, not an established overlap.
4. **Selection objective mismatches use case**: best checkpoint is selected by validation heatmap loss; ai_runtime/xray_structure_runner.py `_calibrate` chooses a per-structure confidence threshold for point-level F1 from the same validation data (grid 0.12, 0.18, 0.24, 0.30, 0.38, 0.48, 0.60). Neither choice directly optimizes exact vertebra count, trait accuracy, or correction effort. Reusing calibration data for reporting can make estimated F1 optimistic.
5. **Repeated count failures are biologically meaningful**: the postprocessor uses local heatmap peaks (3x3 max pooling, per-class threshold) and outputs up to 96 peaks for repeated structures; missed/merged peaks and wrong reference roles can degrade counts and derived traits. Whether the heatmap, threshold, peak detection, or ground-truth convention caused particular misses is **unknown** until examining images and raw scores.
6. **Current report aggregates away the failure mechanism**: app/xray_structure_ai.py `summarize_structure_ai_human_comparison` computes structure and trait summary metrics; UI in app/xray_structures_ui.py does not show per-specimen prediction and annotation, or which vertebrae are missing.

## P0: Establish credible comparisons before changing the network

- Preserve all existing models and project data. Use a copy of the project for development tests.
- Audit membership for v001/v002 and *all reachable ancestors*: overlap by specimen ID, source image ID, and, if available, acquisition session or near-duplicate image. Record missing ancestry/membership as **unknown**, not proof of no leakage.
- Freeze one external set of radiographs, grouped by source plate (and session if needed), never used to train any compared model or its ancestors, or to select hyperparameters. If sufficient external samples are unavailable, create them; do not call existing contaminated validation groups an independent test.
- Evaluate both models on exactly the same frozen images; keep an internal development subset separate from a final untouched test subset. Preserve ground-truth versions and agreement between the two human repeatability readings.
- Add a CSV with one row per specimen/model: human and AI values for tv/abdv/caudv/preDv/preAp, exact correctness, signed error, number of missed/extra points, reference-role errors, counts of low-score candidate peaks, and model metadata. A visual overlay inspection should show both sets of markers and annotate count errors.
- Report per-trait exact accuracy, per-structure count MAE and signed bias, and human annotation repeatability; include sample size and uncertainty intervals. Do not combine related derived traits as if they were statistically independent.

## P1: Cheap reversible inference-only experiments (frozen weights)

1. Cache or regenerate raw probability maps / peak candidates at lower thresholds, *without applying a new threshold to the same final-test data*.
2. Sweep base vertebra confidence threshold and NMS settings on the **development** set, recording missed peaks vs false peaks, exact-count accuracy, MAE, and correction count/time. Include candidates below the present 0.12 calibration floor to test the specific undercount hypothesis.
3. Compare baseline role selection against reference-role ordinal selection constrained to detected vertebral series; separately assess first-caudal and last-predorsal.
4. Preserve model artifacts: changed postprocessing versions should be traceable and reversible. Evaluate only the selected configuration once on the final independent test.

Go/no-go: prioritize improvement in exact-count rate and reduced MAE without material decline in role and downstream trait accuracy. If threshold sweeps do not reduce systematic errors, do **not** keep lowering thresholds blindly.

## P2: Training/data interventions only if P1 fails

- Save epoch-by-epoch train/validation loss and, where feasible, count/role metrics, selected epoch, early-stop reason, threshold settings, seed, source-plate IDs, and model ancestry.
- Investigate misses stratified by body region (especially terminal vertebrae), radiograph contrast, image scale, crowding, and image source. Check annotation consistency with repeated human reads.
- Compare a from-ImageNet baseline vs parent-checkpoint fine-tuning under a fixed leakage-safe split; assess learning curves with increasing training samples rather than relying on successive one-off versions.
- Only then consider architecture/target changes: higher-resolution or tiled inference, density/sequence-aware decoding, hard-example curation, or a count-aware auxiliary objective. Each must beat an inference-only baseline on the same untouched test set.

## Rollout and safety requirements

- Work on branch `experiment/xray-count-diagnostics-20261025`; never modify `main` during experimentation.
- Start with reporting/audit tools and tests, then optional postprocessing feature flags (baseline preserved).
- No mutation of human verification labels, source images, existing model checkpoints or stored original thresholds.
- Require a small reproducible benchmark report, automated unit tests, and explicit review before a pull request is merged.
- This branch's diagnostic document is a plan; it is not a claim that a diagnostic run on the user's actual data has occurred.

## Source pointers

- `ai_runtime/xray_structure_runner.py`: `_Dataset`, `_loss`, `_local_peaks`, `_calibrate`, `train`
- `app/xray_structure_ai.py`: `_verified_truth`, `_split_by_plate`, `prepare_structure_training_dataset`, `train_structure_model`, `compare_structure_model_to_human`, `summarize_structure_ai_human_comparison`
- `app/xray_project.py`: `xray_structure_training_membership`, `structure_model_membership`, `structure_repeatability_metrics`
- `app/xray_structures_ui.py`: `_show_structure_model_comparison`
