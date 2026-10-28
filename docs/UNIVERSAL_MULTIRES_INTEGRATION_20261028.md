# Universal high-resolution Structure AI — integration candidate (28 October 2026)

**Status: implementation in feature branch only; not validated on the Windows application, not activated and NOT released.**

## Scope and scientific boundaries

This change transfers the taxon-INDEPENDENT **inference mechanism** from MorphoLabel-Lab into the canonical application repository. It does **not** transfer Phoxinus-specific biological rules into the engine. The project’s versioned scientific scheme remains the only authority for channels, point roles, count/presence/distance traits and derived formulae.

- A generic repeated marker (vertebral centre, vein junction, cell centre, etc.) can be predicted using full-image and overlapping detail images with weighted heatmap fusion.
- Two trained models can also be combined: native full-image for declared structure channels and native detail for any explicitly declared subset. The selection is a **model metadata policy**, not a hardcoded \`preanal_pterygiophore\` condition.
- The published experimental Phoxinus accuracy cannot be transferred to other objects. Trained weights and thresholds are tied to the training image domain, scientific channel order, acquisition/orientation protocol and source dataset. Other domains require their own training and testing.
- Nothing here makes a point-location model learn a count-only target without verified count-only training. In this version, count-only ptery correction remains an unreleased research feature. The universal engine consumes actual trained heatmap models.

## Clean runtime design

\`ai_runtime/universal_multires.py\` is a separate, opt-in engine. Old models without \`inference_pipeline\` use the exact original \`_decode_one\` in \`xray_structure_runner.py\`. **No global program toggle, no SQLite schema change, no project migration.**

When the following metadata key is present, the built-in backend loads and verifies its extra trained checkpoints once per prediction batch:

\`\`\`json
{
  "inference_pipeline": {
    "name": "multires_heatmap_v1", "version": 1, "mode": "tiled_native",
    "tiles": {"nx": 4, "ny": 2, "width_fraction": 0.38, "height_fraction": 0.62},
    "fusion_weight": 0.6,
    "detail": {
      "checkpoint": "detail.pth", "sha256": "<64 lowercase hex>", "input_size": [768, 384]
    },
    "native": {
      "checkpoint": "native.pth", "sha256": "<64 lowercase hex>",
      "state_prefix": "base.", "input_size": [1536, 512]
    },
    "retain_detail_structures": ["<actual ID from this project's scientific scheme>"]
  }
}
\`\`\`

\`mode=tiled\` omits the native block and returns only fully fused detail+global predictions. Native mode computes fused detail and its own full-image heatmaps, retaining detail channels only when explicitly declared.

The primary baseline \`model.pth\` comes from the original exported Structure AI model. Checkpoint file names are restricted to the local model directory, all additional SHA256 digests are checked, channel IDs and order must match the exact scientific scheme. The original study's detail/full thresholds must come from *frozen tune calibration*, not recalibrated on historically viewed preliminary images.

\`tools/package_universal_multires.py\` constructs an **inactive portable model candidate** from:
1) a standard Structure AI ZIP already exported from the correct project;
2) the trained high-resolution detail checkpoint;
3) optionally, a fully trained Native checkpoint with \`base.\` tensor keys;
4) previously frozen per-channel thresholds JSON.

The builder uses \`torch.load(weights_only=True)\`, requires matching checkpoint tensor schemas and refuses to overwrite existing output. Native is NOT required for an ROI-only package.

Standard GUI **Models… → Import model…** accepts the resulting package. Import refuses to rewrite the project's scientific scheme or orientation. It registers an inactive candidate, marks the previous parent quality metrics as **not applicable** to the composite, and warns before manual activation. The original active model is untouched until an explicit user choice.

## Training is separate

A user who designs a different structure scheme can use the new inference engine after training compatible primary/detail models for that scientific image domain. This patch does NOT yet expose multi-resolution *training* through the general GUI; it exposes a safe, versioned, portable inference path. This is a deliberate scope limit, not a claim of full end-to-end generalization.

## Verification gates before an official release

**Implemented and locally exercised by ChatGPT:** pure geometric tiling, full-frame edge coverage, safe relative checkpoints, hash mismatches, non-fish channel names, deterministic fusion and native channel retention on synthetic 2-structure tests: 12/12 CPU tests; an additional synthetic portable 3-weight package test: 1/1. These isolated tests were run in Python 3.13 / torch CPU and do NOT replace Windows 3.11 application integration. Matching tests were committed under \`tests/test_universal_multires*.py\`. They skip tensor-dependent tests when optional PyTorch is not installed, so core CI does not require CUDA.

**Required on real local Windows app before merge/tag:**
1. Core CI/normal full test suite passes on Python 3.11 without optional PyTorch. Windows packaging CLI/GUI smoke must include \`universal_multires.py\` next to the isolated runner.
2. Original unchanged \`v003\` and legacy model ZIP import/export and ordinary prediction must produce exactly the same result before/after the patch on fixed identical images, including normalized positions, roles, visibility and calculated traits.
3. Build a candidate using exact parent, ROI Detail epoch8 and Native epoch20 CHECKPOINTS with SHA checks, native SHA256 \`5138c843126f2b126d1ff06b2d4315c53d3a1ab484fdf48c87d79e628800c7f4\`. Use true frozen tune thresholds, no new training. Audit reproduction on 32 historical old-preliminary images **after identical masking**: ROI 7/27 ALL7, 24/32 TV; Native 9/27 ALL7,25/32 TV. If any discrepancy, STOP; do not tune to pass.
4. Only then compare inactive candidate alongside currently active v003 on the already verified large local corpus (all confirmed crops, number determined at runtime, NOT presumed 808). Check exact 7 scientific traits with equal denominators, per-source-plate splits, paired corrected/broken and review burden; unverified cases only provide descriptive model disagreements. The historical preliminary is NOT an independent holdout.
5. Non-fish schema smoke test: 2 generic repeated/single structure channels with synthetic checkpoint and known points, plus one genuine non-fish sample only if available and legally usable. Do not promise fish weights will recognize foreign targets.
6. Verify **zero mutation** of original SQLite, images, human VERIFIED annotations, original active weights, production \`main\`; compare SHA256 before/after. Cancel/restart, GPU OOM failure, missing auxiliary weights must fail closed.
7. Independently held-out new source plates are needed before claiming confirmed scientific accuracy or publishing new pre-trained fish model as generally reliable.

### Explicit release decision

Do not merge the feature branch, tag a version, advertise production accuracy or upload trained checkpoints until the gates above are fulfilled. If full integration reproduces the frozen research numbers and the UI's model replacement is safe, proceed to release review. If not, keep the old version as official and fix the actual incompatibility.
