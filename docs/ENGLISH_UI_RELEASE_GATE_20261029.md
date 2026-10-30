# MorphoLabel — English-only user interface release gate

Product decision (2026-10-29): **all MorphoLabel-owned UI text is in English**. This includes all modules, first-run setup, model training and inference, import/export, error/cancellation dialogs, confirmation messages, progress labels, tooltips and Help/About.

Changes already made in branch `fix/release-usability-20261029`:
- All identified Russian-language text in `app/xray_structures_ui.py` was replaced with English without modifying model training, scientific calculations, SQLite, weights or data.
- `tests/test_english_only_interface.py` guards against Cyrillic text in developer-owned Python application string literals.
- No release or main-branch change.

Remaining validation:
1. Run a full repository audit for Cyrillic in user-visible strings, including `app/`, `ai_runtime/`, `tools/` (output surfaced in UI), packaging/onboarding resources and messages returned by plugins. Internal scientific identifiers and human-provided labels must not be rewritten.
2. Test the exact English title and content of each high-resolution Train branch: incompatible parent, existing file, confirmation, preparing, progress, cancellation, error, successful import, failed import, and unvalidated-model activation.
3. Check UI labels at minimum in Landmarks, Crop AI, X-ray Traits, model evaluation, dataset exports, About, installation and first-run AI setup. Confirm string translation has not broken unit tests or changed state.
4. Do not claim Windows OS-owned file dialogs or standard buttons will be English on a Russian-localized operating system. To enforce that everywhere would need a separate custom-dialog localization feature and is not covered by Python string tests.
5. After source/UI audit and green CI, build a **new** Windows distribution from the latest branch commit; installer #41 contains the old Russian text and the old model-lineage bug. Verify the new installer before any publication.

Release gate: all product-owned visible text is English, no new Cyrillic text, no regression in scientific features, and locally verified Windows GUI. Publication only after explicit approval.
