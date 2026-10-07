# QA2 repair validation — 2026-10-07

The fourteen proven findings in the stopped QA2 snapshot are repaired. This is
focused repair validation; the large qualification campaign was not resumed.
The repair starts from `eacacc12a65a02f89867070bdb403995ff16172a` on `main`.
Application version remains `1.0.0-rc.1`. No tag, installer or RC2 release is
published by this repair.

## Findings and independent witnesses

Each finding has a named behavioral regression in
`tests/test_qa2_repair_invariants.py`. Independent reproductions use disposable
projects and the production source application. UI witnesses dispatch Tk button
press/release events on the secondary monitor. They are source GUI evidence,
not installed-candidate or Windows UI Automation coverage.

| ID | Repair and independent result |
| --- | --- |
| QA2-P1-001 | PASS: second TPS exporter writes UTF-8 without BOM atomically. Unicode IMAGE line survives the production Export page; ASCII bytes, precision and ordering remain unchanged. A failed replacement preserves the prior export. |
| QA2-P1-002 | PASS: optional trait/structure display names normalize to abbreviation or ID. Project page renders, reopens and calculates the rectangular-crop angle correctly. Missing scientific references and malformed required fields are rejected at normalization. Cosmetic names do not change scientific identity. |
| QA2-P1-003 | PASS: one typed UI-state boundary rejects invalid mapping/field shapes and logs warnings without scientific writes. Thirty-five independently injected wrong-shape queue states recover; Project and Queues render. Legitimate lists, booleans and Crop coordinate-list proposals remain supported. |
| QA2-P2-001 | PASS: identical coordinates from a new model/run require new confirmation, clear reviewed/verified status and record provenance in correction history. Same observation reapplied retains confirmation. Reopen agrees with training eligibility. |
| QA2-P2-002 | PASS: a complete unfinished manual draft remains in the attention queue until explicit verification; verification removes its draft. |
| QA2-P2-003 | PASS: canonical effective verification includes completeness, unfinished draft, Crop/scheme review and current machine confirmation. Complete drafts stay yellow/unverified after reopen and are ineligible for training. |
| QA2-P2-004 | PASS: attention presentation reclassifies the current item without rewriting the queue. The production action says Verify & Next when verification is required; resolved-item Next only navigates. |
| QA2-P1-004 | PASS: Landmark imports store canonical inference_config.py, with an explicitly declared legacy config.py fallback for existing imports. A → B activation/reopen/re-export → C activation/actual 25-point prediction succeeds with unchanged config/checkpoint hashes. |
| QA2-P2-005 | PASS: successful X-ray Predict current refreshes only the affected sidebar row. Actual 38-marker prediction immediately shows Draft/yellow; selection, scroll and reopened persistence agree. |
| QA2-P1-005 | PASS: managed workers use the managed Python directory rather than frozen _internal. Useful-progress deadlines ignore repeated 0/N heartbeats; Cancel terminates the owned Windows process tree. Real frozen-like GPU preflight completes in 47.422 s, cuda:0, batch 2, workers 4. |
| QA2-P3-001 | PASS: completion and model manager share the saved engineering-validation reader. The real one-epoch witness saves P90=67.15846222782574%, and both readers use that value (this short run is a workflow test, not model-quality certification). |
| QA2-P2-006 | PASS: browsing another calibration image is separate from the persisted reference. Cancel retains A; Save commits B; reopen displays B. |
| QA2-P2-007 | PASS: calibration save uses the existing count invalidation/Measurements refresh path. The production page changes immediately from Calibrated 0/1 to 1/1 and retains calibration after reopen. |
| QA2-P1-006 | PASS: an initial annotation batch no longer depends on a repeatability control set. The production first-batch workflow persists six IDs, registers a queue, resumes after reopen and advances after explicit verification. Existing-control regressions pass. |

## Neighbor audit and scientific safety

The audit covered forced-ASCII Landmark exporters, optional scheme labels,
mapping-valued UI queues, verification/training/QC/list consumers, attention
navigation, portable config naming, current-item X-ray mutation refresh paths,
all sibling managed-worker launch directories, progress deadlines, metric
readers, calibration refresh and training stage derivation. Changes reuse the
existing architecture and storage contracts.

Focused source tests pass for all four portability families: Landmark Crop,
Landmark AI, X-ray Crop/orientation and X-ray Structure. Real Landmark AI evidence
additionally includes imported-parent continued training, registered child
lineage, explicit child activation, reopen and actual 25-point prediction.
All three imported-parent artifact hashes remain unchanged. These results do
not claim completion of the stopped four-family installed GUI qualification.

Original-coordinate/history/correction-history, manual protection, training
eligibility, repeatability isolation, model lineage, schema compatibility and
verified-only export regressions pass. UI recovery does not rewrite scientific
records. Historical scheme identity is preserved: presentation defaults do not
inject new scientific rule/structure defaults.

Original protected-file SHA256/size/file-set comparisons are UNCHANGED:
31 X-ray project files, 11,319 Landmark project files, 653 X-ray source images,
1,304 external Landmark images; total 13,307. The pre-existing baseline excludes
project cache/source/backups/migration logs/diagnostics; source images are
checked separately. Original research projects were not intentionally written.

## Validation

- Python compilation: all 211 Python files under app, ai_runtime and tools PASS.
- Focused final run: 309 tests, 0 failures, 0 errors, 0 skips, 194.771 s.
- Full final run: 1,210 tests, 0 failures, 0 errors, 1 unchanged optional skip,
  358.819 s, PASS. The skip is the optional first-model RTMPose bootstrap fixture
  when its assets are absent; the real imported-parent runtime witness ran.
- Independent minimized witnesses: 14/14 PASS; production source Tk callback errors: zero.
- Real imported RTMPose continued training and subsequent child prediction: PASS.
- Frozen-like proof: real training preflight with the backend module location
  set to candidate _internal, plus a deliberately conflicting foreign module
  fixture and a bounded endless 0/4 heartbeat fixture. No new PyInstaller build
  was needed for this proof. Worker counts 2 and 4 were actually probed.
- Owned parent/descendant cancellation: PASS in 0.900 s outside the restricted
  tool sandbox; Windows taskkill is denied inside that sandbox.

Earlier full runs exposed two tests enforcing superseded semantics (new-run
confirmation and attention cache trust) and one legitimate Crop proposal-shape
regression introduced during the typed-state repair. The semantics tests now
assert both old-observation preservation and new-run invalidation/current-only
classification; coordinate-list proposals are supported and have a regression.
Final evidence below supersedes those intermediate runs. Existing suite
ResourceWarnings and Tk teardown messages are retained in local logs.

Local evidence is under `D:\_Temp\MorphoLabel_QA2`: repair2_checkpoint.md,
repair2_final_unittest.log, repair2_focused_final.log,
repair2_independent/summary.json, repair2_runtime/summary.json and
repair2_original_data_integrity.txt. Harnesses, private baselines, project DBs,
images, weights, candidate builds and raw logs are not included in the commit.

All mandatory repair validation passed. Release status: READY FOR RESIDUAL QA2.
This repair does not certify the uncompleted installer/upgrade and remaining
installed GUI qualification phases.
