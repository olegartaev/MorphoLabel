# MorphoLabel — universal high-resolution continued training (28 October 2026)

**Status: development branch only. Not yet exposed by the normal Train button. No local GPU training performed by ChatGPT.**

## Existing user situation

The user has confirmed that imported `morpholabel_native_roi_ptery_test_v1` works visibly better in a copied project. The original active `xray_structure_model_v003` must remain intact during this step. The current GUI **Train** still calls standard 768×256 ResNet18 training, even if the selected parent is a multiresolution model; do NOT suggest this already retrains the composite.

## Implemented by ChatGPT

- `ai_runtime/universal_multires_training_data.py` — derives full-coverage high-res overlapped tiles using the project's existing verified points, roles, and visibility; train/validation separation is inherited at **source-plate** level; generic scientific channel names only; no manual remarking; no modifications to original crops.
- `ai_runtime/xray_structure_runner.py` — compatible optional `learning_rate` and `fixed_thresholds` arguments, preserving ordinary training defaults. Low-rate fine-tuning avoids resetting the successful model and prevents misleading tile-only threshold tuning.
- `tools/train_universal_multires.py` — takes **explicit project COPY** and the existing hybrid model ID, exports old model into scratch, creates plate-separated verified training sets, separately continues full Native 1536×512 and ROI Detail 768×384 learning using their own **trained** weights, then writes **one INACTIVE portable model ZIP** with unchanged parent checkpoint, scientific contract and threshold policy, new SHA256-locked Native and Detail weights, precise local provenance. It does **not** register, activate, edit verified labels, or write to the project database.
- `tests/test_universal_multires_training_data.py` and `tests/test_universal_multires_training_package.py` — source-plate leakage, generic non-fish structures, visibility, non-destructive inputs, ZIP hashes and no overwrites.

This is **continued learning for existing multiresolution models**, domain-neutral by structure ID. It is **not yet training a fully new hybrid from ImageNet**; a new unrelated biological schema would first need a compatible base/high-res model or an extra automated bootstrap step.

## Single local CUDA test — no architectural invention

1. In an independent worktree use branch `feature/universal-multires-training-20261028` of `olegartaev/MorphoLabel`. Use the same working PyTorch CUDA environment and RTX 3060 established in the completed 142-fish research. Keep the original MorphoLabel project untouched.
2. Create an independent project **copy** containing the existing working `morpholabel_native_roi_ptery_test_v1`, and verify original SQLite, original active v003, source TIFF, old weights SHA256 BEFORE/AFTER. Use `--project-copy` only on that copy.
3. Run core Python tests first, then exact one GPU job (no tuning). Command from canonical repository root:
   ```bat
   python tools/train_universal_multires.py --project-copy "<PROJECT_COPY_ROOT>" --source-model morpholabel_native_roi_ptery_test_v1 --output "<EXTERNAL_NEW_DIRECTORY>\multires_retrained_candidate.zip" --epochs-native 18 --epochs-detail 18 --device cuda:0
   ```
   Do not specify the **original live** project root. Split by source plates, ~80% train / 20% validation; count exact records from the actual current project. Original successful weights are used as warm starts. Prior frozen thresholds are preserved. No new manual labels.
4. Import the resulting ZIP into a **fresh project copy** as inactive. Check scientific channel order, orientation, all auxiliary SHA256, package import/export, GPU prediction on 32 historical cases and on previously verified examples (do not count overlap as independent science). Paired comparison against original hybrid is essential for confirming the new model doesn't regress. Report ALL7, TV/abdv/predv/preap and rare ptery classes + corrected/broken for the exact same cases.
5. New data **must not be used twice as if independent**. Because old weights have already seen earlier 81/29 material, re-splitting them by plates does not create a scientifically independent holdout. For generalization, reserve previously unseen source plates, if present. Otherwise report developmental metrics only and keep candidate inactive.
6. After local integration is technically PASS and new model shows no significant new error, make a carefully labeled GUI **Train high-resolution** option using the existing verified dataset and parent model, with safe inactive output, cancel/progress/error handling. Maintain existing **Train** behavior unchanged. Do not merge or publish release yet.

Stop on failures of scientific contract, dataset provenance, checkpoint load or 32-case reproduction; fix minimal technical issues and do not silently fall back to legacy training. Deliver exact path to portable model ZIP, paired metrics, any regression and source protection report.

## Not goals

- No fresh labeling of hundreds of X-rays.
- No starting backbone from scratch or new model architecture.
- No tuning epochs/thresholds to win a historically observed preliminary benchmark.
- No changes to production `main`, no release, no automatic replacement of v003.
