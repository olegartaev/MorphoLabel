# Contributing to MorphoLabel

Bug reports and feature proposals should use GitHub Issues. Pull requests should explain the user-visible change, include focused tests, and keep the repository runnable from a clean checkout.

Changes to scientific behavior, landmark identity, coordinate transforms, project formats, QC semantics, or training data handling require explicit discussion before implementation. Do not include private specimens, original photographs, credentials, model weights, or generated project data in commits.

Run the focused contract test and relevant deterministic tests locally before opening a pull request:

```text
python -m unittest tests/test_morpholabel_ui_contract.py
```

Keep changes small, document provenance-affecting behavior, and avoid force-pushing shared branches.
