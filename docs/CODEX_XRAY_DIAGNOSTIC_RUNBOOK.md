# Local X-ray diagnosis via low-cost Codex: runbook

Branch: `experiment/xray-count-diagnostics-20261025`
Scope: **diagnosis before retraining**. Production `main` and all user data stay unchanged.

## Purpose

The user has models v001, v002, v003 and verified manual vertebral annotations on a local Windows workstation. We need to distinguish a heatmap-learning limitation from confidence thresholds, peak extraction, image scale, human annotation conventions, and role assignment. A human reviewer will interpret outputs. Codex should **implement and execute deterministic local Python analyses**, not spend tokens reasoning repeatedly about individual images.

See `docs/XRAY_STRUCTURE_COUNT_DIAGNOSTICS.md` for verified source-code audit and user-supplied baseline metrics.

## Safety and data ownership

1. Ensure `git branch --show-current` is `experiment/xray-count-diagnostics-20261025`; otherwise stop. Do not commit or merge into `main`.
2. Locate the user's actual X-ray project **only using a path the user provides**, not broad filesystem scans.
3. Read project SQLite via a read-only connection or a safe, explicitly created copy. Never alter original radiographs, crops, annotations, scores, checkpoints, model metadata, or the original project database.
4. Do not upload local radiographs, patient/field identifiers, specimen codes, filenames, coordinates, annotations, raw outputs, databases, or model checkpoints to a public repository. The repository is public. Local detailed reports live in gitignored `reports/` (or `diagnostics/`).
5. Do not auto-push data-derived reports. Only an explicitly reviewed, genuinely aggregated, non-identifying summary may be copied to a tracked Markdown file and pushed after the user approves.
6. Restrict changes to diagnostic scripts/tests/docs and reversible experimental switches; keep existing defaults unchanged. Do not install unknown packages or bypass sandbox/approval rules.

## Execution: Phase A, mandatory and cheap

- Read only the relevant files: `app/xray_structure_ai.py`, `app/xray_project.py`, `ai_runtime/xray_structure_runner.py`, `app/xray_schema.py`, `tests/test_xray_structure_ai.py`. Read further only for a specific reason.
- Validate selected project path, presence of model v003, readable `xray_project.sqlite3`, and matching X-ray scheme. If missing, print an actionable blocker and stop without fabricating results.
- Generate local model ancestry + validation contamination audit: enumerate parent links and train/validation memberships for each model; detect whether a selected comparison specimen or its source image appears in any model's own train or ancestor train. Classify `contaminated`, `confirmed unseen among recorded models`, or `unknown due to missing membership`. Distinguish within-run plate separation from across-run lineage leakage.
- Build a common set of human-verified specimens, report how many are eligible for all three models, how many have unambiguous lineage-clean provenance, and whether this is a **development diagnostic**, not an independent generalization test. If fewer than adequate clean specimens exist, state the limitation rather than silently using model-specific validation samples.
- Run each model on the **same** local specimens, using the project's existing backend, without changing saved predictions or human labels. Write per-specimen CSV locally containing actual count/trait values, signed errors, count exactness, role ordinal errors, local peak misses/extras, and source image groups. If a comparison is not possible, explain precisely why.
- Produce aggregate Markdown + CSV and plots, labelled by model, dataset cohort, and provenance. Include `tv`, `abdv`, `caudv`, `preDv`, `preAp`, raw repeated counts, count MAE, signed count bias, exact-count, role ordinal accuracy and failure breakdown. Separate dependent derived traits; do not treat them as independent trials.
- Store computational provenance: git SHA, model ID, scheme digest, number of source plates, specimen count, training ancestry audit outcome, chosen thresholds, date, and any read-only project snapshot checksum if feasible. Never include source image paths/codes in public summary.
- Run narrowly relevant existing tests plus new unit tests using synthetic data. Report passing/failing tests without hiding errors.

## Phase B: small, controlled inference-only sweep (if Phase A succeeds)

- Keep weights fixed; avoid training.
- Use one shared **development/calibration** subset for thresholds and a separate untouched held-out subset if sufficient previously unseen source plates exist. Never tune against the final test set.
- Examine actual heatmap/peak-score candidates at lower thresholds. Test current thresholds and a small sweep (e.g. 0.02, 0.05, 0.08, 0.12, 0.18, 0.24, 0.30) alongside original thresholds; optionally test peak separation / NMS settings **only after** identifying missed points. A lower threshold does not recover a peak that was never proposed.
- Diagnose matched vs missed vertebrae, false positives, vertebral start/end, neighboring-peak suppression, role ordinal errors, and per-structure differences. Report exact count, MAE, bias and additional manual corrections required. Do not optimize only macro F1.
- Cache raw predictions/maps once per specimen where possible: run expensive forward pass once, then sweep cheap decoding in Python.
- Report all alternatives, including non-improvements or worse false positives, in a compact table. Do not quietly update original model thresholds or the default predictor.

## Phase C (NOT part of this first run)

No retraining, architecture migration, hyperparameter search or new dependencies until a reviewer approves Phase A/B evidence.

## Local outputs (all gitignored)

- `reports/xray_count_diagnostics/README.md`: a concise, self-contained diagnostic report, actual sample sizes and limitations
- `reports/xray_count_diagnostics/model_ancestry_audit.csv`
- `reports/xray_count_diagnostics/per_specimen_local.csv`
- `reports/xray_count_diagnostics/summary.csv`
- `reports/xray_count_diagnostics/threshold_sweep.csv` (if Phase B is possible)
- `reports/xray_count_diagnostics/figures/` for plots (if useful)

Only share or commit `docs/experiments/xray_count_diagnostics_summary.md` **after the user reviews it** for anonymity and accuracy; do not create that file automatically from raw identifiers. Provide the reviewer the report in the local folder, or user-approved sanitized GitHub summary, plus any relevant test commit hash.

## Stop / quality gates

Stop instead of guessing when the project root, model artifacts, reference annotations or cross-model comparable cohort is missing. Stop if performance measurements require modifying originals. Keep the report honest about parent-trained validation contamination; only a truly untouched held-out test can support generalization claims.

## Suggested Codex task (copy into Codex)

> Work on branch `experiment/xray-count-diagnostics-20261025`. Read `docs/CODEX_XRAY_DIAGNOSTIC_RUNBOOK.md` and `docs/XRAY_STRUCTURE_COUNT_DIAGNOSTICS.md`. My local MorphoLabel X-ray project is at: [PASTE ABSOLUTE PATH]. Implement and run only Phase A, then Phase B if safe and feasible. Minimize model tokens: write deterministic Python scripts, run them locally, no subagents, no network research, no retraining, no broad refactor. Save all detailed outputs under gitignored reports/, preserve all project data/model files, add focused tests, and return a concise summary with diagnostic findings, unknowns, exact output paths, and any tests run. Do not push results or merge branches.
