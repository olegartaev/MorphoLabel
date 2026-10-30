"""Release contract: developer-owned application text is English only.

Only string literals are checked: Cyrillic in comments or user-imported data
is not treated as UI text. Explicit UI localisation can replace this contract
if multi-language support is added in the future.
"""
from __future__ import annotations

import io
from pathlib import Path
import re
import tokenize
import unittest

CYRILLIC = re.compile("[\\u0400-\\u052F]")
APP = Path(__file__).resolve().parents[1] / "app"
REPO_ROOT = APP.parent
USER_TEXT_ROOTS = (APP, REPO_ROOT / "ai_runtime", REPO_ROOT / "tools")


def find_non_english_string_literals(root=APP):
    found = []
    for path in sorted(root.rglob("*.py")):
        # tokenize.open understands UTF-8 BOM / PEP-263 source encodings.
        with tokenize.open(path) as stream:
            source = stream.read()
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.STRING and CYRILLIC.search(token.string):
                found.append((str(path.relative_to(root)), token.start[0]))
    return found


class EnglishOnlyInterfaceTests(unittest.TestCase):
    def test_all_user_facing_package_string_literals_are_english(self):
        violations = [
            (f"{root.name}/{path}", line)
            for root in USER_TEXT_ROOTS
            if root.exists()
            for path, line in find_non_english_string_literals(root)
        ]
        self.assertEqual(violations, [], (
            "Unexpected Cyrillic in developer-owned user-facing strings. "
            "Translate buttons, dialog titles, progress text and errors: "
            + repr(violations[:50])
        ))

    def test_checker_ignores_comments_but_detects_dialogs(self):
        with __import__("tempfile").TemporaryDirectory() as temp:
            root=Path(temp)
            (root/"test.py").write_text(
                "# Комментарий для разработчика\n"
                "label='Training ready'\n", encoding="utf-8")
            self.assertEqual(find_non_english_string_literals(root), [])
            (root/"test.py").write_text(
                "label='Обучение'\n", encoding="utf-8")
            self.assertEqual(find_non_english_string_literals(root), [("test.py", 1)])


if __name__=="__main__":
    unittest.main()
