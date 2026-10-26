"""Connection loss must update the shipped frontend's shared state and capture UI."""

from pathlib import Path
import subprocess
import unittest


class LiveStatusUITests(unittest.TestCase):
    def test_status_invalidates_shared_connection_and_capture_controls(self):
        script = Path(__file__).with_name('live_status_ui.mjs')
        result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
