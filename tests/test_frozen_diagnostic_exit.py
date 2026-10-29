import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ENTRYPOINT = Path(__file__).resolve().parents[1] / 'packaging' / 'entrypoint.py'


class FrozenDiagnosticExitTests(unittest.TestCase):
    def test_diagnostic_failure_keeps_report_and_exits_without_unhandled_exception(self):
        for joined_option in (False, True):
            with self.subTest(joined_option=joined_option), tempfile.TemporaryDirectory() as temp:
                report = Path(temp) / 'failure.json'
                args = ['MorphoLabel.exe', '--ai-self-test']
                args += [f'--diagnostic-report={report}'] if joined_option else ['--diagnostic-report', str(report)]
                with patch('sys.argv', args), patch('app.self_test.run_ai_self_test', side_effect=RuntimeError('missing test asset')):
                    with self.assertRaises(SystemExit) as result:
                        runpy.run_path(str(ENTRYPOINT), run_name='__main__')
                self.assertEqual(1, result.exception.code)
                import json
                data = json.loads(report.read_text())
                self.assertEqual('FAIL', data['status'])
                self.assertEqual('missing test asset', data['error'])

    def test_normal_gui_errors_keep_existing_reporting(self):
        with patch('sys.argv', ['MorphoLabel.exe']), patch('app.__main__.main', side_effect=RuntimeError('GUI failure')):
            with self.assertRaisesRegex(RuntimeError, 'GUI failure'):
                runpy.run_path(str(ENTRYPOINT), run_name='__main__')

    def test_successful_diagnostic_keeps_zero_exit(self):
        with patch('sys.argv', ['MorphoLabel.exe', '--ai-self-test', '--diagnostic-report=report.json']), patch('app.__main__.main', return_value=0):
            with self.assertRaises(SystemExit) as result:
                runpy.run_path(str(ENTRYPOINT), run_name='__main__')
        self.assertEqual(0, result.exception.code)


if __name__ == '__main__':
    unittest.main()
