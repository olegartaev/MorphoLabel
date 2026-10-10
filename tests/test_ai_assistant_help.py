"""Focused checks for single-level Support / AI assistant help."""
import tkinter as tk
from tkinter import font as tkfont, ttk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.ui.shell import ProductionShell, AI_HELP_PROMPT, USER_GUIDE_URL


class AIAssistantPublicContractTests(unittest.TestCase):
    def test_public_prompt_contains_only_references_and_question(self):
        self.assertEqual(
            AI_HELP_PROMPT,
            "Help me use MorphoLabel. Consult the public User Guide and source code, then explain the steps clearly for a non-programmer. If you cannot verify a detail, say so rather than guessing.\n\n"
            "User Guide: https://github.com/olegartaev/MorphoLabel/blob/main/docs/USER_GUIDE.md\n\n"
            "Source code: https://github.com/olegartaev/MorphoLabel\n\n"
            "My question:",
        )
        self.assertTrue(USER_GUIDE_URL.startswith("https://github.com/olegartaev/MorphoLabel/"))
        guide=(Path(__file__).resolve().parents[1]/"docs"/"USER_GUIDE.md").read_text(encoding="utf-8")
        self.assertIn("## 12.9 Getting help from an AI assistant",guide)
        self.assertIn("Menu → Help with an AI assistant…",guide)


class AIAssistantTkTests(unittest.TestCase):
    def setUp(self):
        try:
            with patch("app.ui.shell.first_run_setup_required",return_value=False):
                self.shell=ProductionShell()
        except tk.TclError as exc:
            self.skipTest(f"Tk desktop unavailable: {exc}")
        self.addCleanup(self.shell.destroy)
        self.shell.update_idletasks()

    def _buttons(self,parent):
        found=[]
        for child in parent.winfo_children():
            if isinstance(child,ttk.Button):
                found.append(child)
            found.extend(self._buttons(child))
        return {button.cget("text"):button for button in found}

    def test_flat_menu_order_bold_help_and_original_actions(self):
        row=ttk.Frame(self.shell);row.pack()
        self.shell._menus(row)
        menu_button=next(w for w in row.winfo_children() if isinstance(w,ttk.Menubutton))
        menu=self.shell.nametowidget(menu_button.cget("menu"))
        kinds=[menu.type(i) for i in range(menu.index("end")+1)]
        self.assertNotIn("cascade",kinds)
        labels=[menu.entrycget(i,"label") for i in range(len(kinds)) if kinds[i]=="command"]
        self.assertEqual(
            ["Help with an AI assistant…","User Guide","Set up AI support...","Hardware status…",
             "Create diagnostic report…","GitHub project","About MorphoLabel..."],
            labels,
        )
        self.assertEqual("bold",tkfont.Font(root=self.shell,font=menu.entrycget(0,"font")).actual("weight"))
        self.assertEqual("normal",menu.entrycget(0,"state"))

    def test_dialog_copy_guide_and_close_are_real_tk_commands(self):
        dialog=self.shell.show_ai_assistant_help()
        self.shell.update_idletasks()
        self.assertEqual("Help with an AI assistant",dialog.title())
        labels=[child.cget("text") for child in dialog.winfo_children()[0].winfo_children() if isinstance(child,ttk.Label)]
        self.assertIn("Need help using MorphoLabel?",labels)
        self.assertIn(
            "AI answers may be incorrect. Verify scientific decisions and avoid sharing confidential research data.",
            labels,
        )
        buttons=self._buttons(dialog)
        self.assertEqual({"Copy AI help prompt","Open User Guide","Close"},set(buttons))
        buttons["Copy AI help prompt"].invoke()
        self.assertEqual(AI_HELP_PROMPT,self.shell.clipboard_get())
        with patch("app.ui.shell.webbrowser.open",return_value=True) as opened:
            buttons["Open User Guide"].invoke()
        opened.assert_called_once_with(USER_GUIDE_URL)
        buttons["Close"].invoke()
        self.assertEqual(0,dialog.winfo_exists())


if __name__=="__main__":
    unittest.main()
