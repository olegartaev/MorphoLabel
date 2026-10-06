"""Project setup keeps the catalog visible while settings scroll independently."""
import unittest
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tests import test_final_functional_hardening as fixtures


def walk(parent):
    for child in parent.winfo_children():
        yield child
        yield from walk(child)


class ProjectSetupLayoutTests(unittest.TestCase):
    setUp = fixtures.FinalTkHardeningTests.setUp
    make_shell = fixtures.FinalTkHardeningTests.make_shell

    def check_module(self, module, catalog_title, source_title):
        shell, errors = self.make_shell()
        shell.deiconify()
        for scale, width, height in ((1.333, 1400, 900), (1.667, 1400, 900), (2.0, 1400, 900), (2.0, 980, 650)):
            shell.tk.call('tk', 'scaling', scale)
            shell.geometry(f'{width}x{height}')
            shell.open_module(module)
            runtime = shell._active_module_runtime
            if module == 'landmarks':
                runtime.select('project')
            else:
                runtime._select('project')
            for _ in range(8):
                shell.update_idletasks(); shell.update()
            widgets = list(walk(shell))
            catalog = next(w for w in widgets if w.winfo_class() == 'TLabelframe' and w.cget('text') == catalog_title)
            source = next(w for w in widgets if w.winfo_class() == 'TLabelframe' and w.cget('text') == source_title)
            self.assertGreater(catalog.winfo_rootx(), source.winfo_rootx() + source.winfo_width())
            self.assertLessEqual(catalog.winfo_rootx() + catalog.winfo_width(), shell.winfo_rootx() + shell.winfo_width())
            self.assertLessEqual(catalog.winfo_rooty() + catalog.winfo_height(), shell.winfo_rooty() + shell.winfo_height())
            canvases = [w for w in widgets if w.winfo_class() == 'Canvas' and source in list(walk(w))]
            self.assertTrue(canvases, 'Settings have their own scroll viewport')
            viewport = canvases[0]
            # Hosted Windows runners can clamp the requested geometry. The
            # catalog must remain visible and fill the available column; its
            # absolute pixel height depends on the desktop's work area.
            self.assertGreater(catalog.winfo_height(), 140)
            self.assertGreaterEqual(catalog.winfo_rooty(), viewport.winfo_rooty() - 2)
            self.assertLess(catalog.winfo_rooty() - viewport.winfo_rooty(), 130)
            self.assertLess(abs(catalog.winfo_rooty() + catalog.winfo_height() - viewport.winfo_rooty() - viewport.winfo_height()), 3)
            settings_buttons = [w for w in walk(viewport) if w.winfo_class() == 'TButton']
            for button in settings_buttons:
                button.focus_force()
                for _ in range(3): shell.update_idletasks(); shell.update()
                self.assertGreaterEqual(button.winfo_rooty(), viewport.winfo_rooty() - 1)
                self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), viewport.winfo_rooty() + viewport.winfo_height() + 1)
            self.assertEqual([], errors)

    def test_landmark_samples_fill_main_column_at_all_scales(self):
        self.check_module('landmarks', 'Samples', 'Source photos')

    def test_xray_traits_fill_main_column_at_all_scales(self):
        self.check_module('xray_counts', 'Traits', 'Source X-rays')


class WindowlessLauncherTests(unittest.TestCase):
    def test_desktop_launch_detaches_and_vbs_hides_the_console(self):
        root = Path(__file__).resolve().parents[1]
        command = (root / 'START_APP.cmd').read_text(encoding='utf-8')
        self.assertIn('wscript.exe', command)
        self.assertNotIn('pause', command)
        launcher = (root / 'START_APP.vbs').read_text(encoding='utf-8')
        self.assertIn('RUN_CANONICAL.cmd', launcher)
        self.assertIn(', 0, True)', launcher)
        self.assertIn('MorphoLabel-startup.log', launcher)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows desktop launcher')
    def test_real_script_quotes_paths_logs_canonical_command_and_hides_console(self):
        from app.process_utils import hidden_window_kwargs
        with tempfile.TemporaryDirectory(prefix='MorphoLabel GUI путь ') as directory:
            root = Path(directory)
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'START_APP.vbs', root / 'START_APP.vbs')
            (root / 'probe.py').write_text(
                'import ctypes\n'
                'hwnd=ctypes.windll.kernel32.GetConsoleWindow()\n'
                'print("VISIBLE="+str(bool(ctypes.windll.user32.IsWindowVisible(hwnd))))\n', encoding='utf-8')
            (root / 'RUN_CANONICAL.cmd').write_text(
                f'@echo off\necho canonical:%1\n"{sys.executable}" "%~dp0probe.py"\nexit /b %ERRORLEVEL%\n', encoding='utf-8')
            env = dict(os.environ, TEMP=str(root), TMP=str(root))
            result = subprocess.run(['cscript.exe', '//nologo', str(root / 'START_APP.vbs')],
                                    env=env, capture_output=True, timeout=15, **hidden_window_kwargs())
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            log = (root / 'MorphoLabel-startup.log').read_text(encoding='utf-8')
            self.assertIn('canonical:shell', log)
            self.assertIn('VISIBLE=False', log)


if __name__ == '__main__':
    unittest.main()
