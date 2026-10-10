"""Minimal, independent credits for core and future MorphoLabel modules."""
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from app.identity import APP_CREATOR, COPYRIGHT, LICENSE_NAME
from app.extensions.api import ModuleSpec, EXTENSION_API_VERSION
from app.ui.module_credits import module_credit_rows, visible_module_author
from app.ui.shell import ProductionShell


class CreditsMetadataTests(unittest.TestCase):
    def test_existing_modules_keep_author_metadata_without_repetition(self):
        from app.extensions.builtins import module_registry
        with patch("app.ui.module_credits._landmarks_ai",return_value="Landmark AI"), patch("app.ui.module_credits._xray_ai",return_value="X-ray AI"):
            rows=module_credit_rows(module_registry())
        self.assertEqual(2,len(rows))
        self.assertEqual([APP_CREATOR,APP_CREATOR],[row[1] for row in rows])
        self.assertTrue(all(visible_module_author(row[1]) is None for row in rows))
        self.assertEqual("Module author: Jane Smith",visible_module_author("Jane Smith"))
        self.assertIsNone(visible_module_author(""))
        self.assertIsNone(visible_module_author("See module documentation"))

    def test_public_module_spec_accepts_optional_author_without_breaking_old_constructors(self):
        base=("test_science","New science module","Example","1",EXTENSION_API_VERSION,99,"available",lambda:None,"external")
        legacy=ModuleSpec(*base)
        self.assertIsNone(legacy.author)
        with_credit=ModuleSpec(*base,author="Jane Smith")
        class Registry:
            def available(self):
                return (with_credit,legacy)
        rows=module_credit_rows(Registry())
        self.assertEqual("Jane Smith",rows[0][1])
        self.assertEqual("See module documentation",rows[1][1])
        self.assertEqual("Module author: Jane Smith",visible_module_author(rows[0][1]))
        self.assertIsNone(visible_module_author(rows[1][1]))


class AboutCreditsTkTests(unittest.TestCase):
    def setUp(self):
        try:
            with patch("app.ui.shell.first_run_setup_required",return_value=False):
                self.shell=ProductionShell()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        self.addCleanup(self.shell.destroy)
        self.shell.update_idletasks()

    def _label_texts(self,widget):
        labels=[]
        for child in widget.winfo_children():
            if isinstance(child,ttk.Label):
                labels.append(child.cget("text"))
            labels.extend(self._label_texts(child))
        return labels

    def test_about_credits_distinct_external_module_without_duplicate_core_author(self):
        class Runtime:
            def render(self,host):
                pass
            def close(self):
                pass
        self.shell.module_registry.register(ModuleSpec(
            "third_science","Other research module","Example analysis","1",
            EXTENSION_API_VERSION,90,"available",Runtime,"external",author="Jane Smith",
        ))
        with patch("app.ui.shell.center"):
            dialog=self.shell.show_about()
        self.addCleanup(dialog.destroy)
        labels=self._label_texts(dialog)
        self.assertEqual(1,sum(text==APP_CREATOR for text in labels))
        self.assertIn("Module author: Jane Smith",labels)
        self.assertNotIn(f"Module author: {APP_CREATOR}",labels)
        self.assertIn(f"License: {LICENSE_NAME}",labels)

    def test_home_page_copyright_remains_subtle_and_visible(self):
        self.shell.geometry("1280x720")
        self.shell.update()
        labels=self._label_texts(self.shell)
        self.assertEqual(1,labels.count(f"{COPYRIGHT} · {LICENSE_NAME}"))


if __name__=="__main__":
    unittest.main()
