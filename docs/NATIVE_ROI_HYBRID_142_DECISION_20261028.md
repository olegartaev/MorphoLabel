# Decision after real 142-fish resolution experiment (28 Oct 2026)

**Production release: NOT YET. Experimental candidate: YES.**

Source, private research branch: `olegartaev/MorphoLabel-Lab`, `research/full-vs-tiles-vs-combined-20261028`, file `results/EX-20261028-FULL-VS-TILES-VS-FUSED/REPORT_RU.md`. Real GPU inference on 142 frozen verified crops, original weights, historic 32 gate passed. 117 fish with all seven traits evaluable.

| Pipeline | ALL7 | TV | PreAp |
|---|---:|---:|---:|
| ROI Detail 8 tiles + parent | 33/117 | 89/142 | 59/120 |
| Native full 1536x512 | 33/117 | 109/142 | 42/120 |
| Native full + ROI heatmap fusion | 33/117 | 106/142 | 41/120 |
| **Native full + ROI Detail preanal ptery points** | **44/117** | **109/142** | **59/120** |
| Existing active v003 (research protocol, not GUI reprediction) | 3/117 | 16/142 | 17/120 |

Native/ROI hybrid fixed 12 complete ALL7 specimens and broke 1 relative to ROI Detail. TUNE: 6/22 vs 6/22 (no win); OLD preliminary: 9/27 vs 7/27; TRAIN: 29/68 vs 20/68 but these fish were used in model training. The entire 142-fish corpus has NO independent prospective holdout. **No claim of confirmed population generalization.**

Rare preanal ptery counts: hybrid 3=1/7, 4=28/52, 5=30/55, 6=0/6; this remains materially short of reliable counting. Normal 8-tile/native HEATMAP fusion is worse or equal, so it should NOT be introduced as default. The prior hybrid is a selective **structure-channel override**; this is already supported by the generic multires `mode=tiled_native` and `retain_detail_structures`. The metadata for this Phoxinus model must use `retain_detail_structures:["preanal_pterygiophore"]`. Other scientific schemas select their own channels; never hardcode fish names in the generic engine.

## Remaining immediate engineering — small one-shot local action (no training)

1. Use existing frozen original trained targeted_warm base `model.pth` + ROI Detail epoch8 checkpoint + Native full epoch20 checkpoint; verify native SHA256 `5138c843126f2b126d1ff06b2d4315c53d3a1ab484fdf48c87d79e628800c7f4`. Use exact previously frozen ROI thresholds, channel order/metadata scientific scheme.
2. With `tools/package_universal_multires.py` create one portable `mode=tiled_native` candidate (inactive). Export a standard Structure AI base package with targeted_warm (not the current active v003!) plus original scheme. Keep all inputs and DB unchanged.
3. In an ISOLATED copy of the app project, import the candidate, verify that model is inactive, compare its point sets and all7 traits on the SAME historical 32 images against the proven read-only research implementation. Demand exact reproducibility of 9/27 ALL7, 25/32 TV under the same disputed-case masking. Then smoke 20-30 non-train real oriented crops with side-by-side proposals (descriptive only without independent human verified labels). Confirm current v003 remains unchanged and individually produces same predictions pre/post patch. Investigate any enormous differences in v003 TV rather than automatically declaring it invalid.
4. Ensure packaged app can invoke standalone `ai_runtime/universal_multires.py` and has working model ZIP import/export. Full Windows core CI has completed **success** for feature commit `4dcc449236cfe2630fa0cd7adceaa6fde9e5bc07`. GPU runtime and full Windows packaging for new feature are not yet verified.
5. Report concise PASS/FAIL, paths to the locally created candidate and viewer, number of specimens compared, any inference/compatibility errors. No code rewriting unless a reproducible technical incompatibility, no threshold tuning, no training, no new architecture, no main merge, no official release.

Keep Draft PR https://github.com/olegartaev/MorphoLabel/pull/4 unmerged until it passes real executable smoke and identical scientific outputs.
