"""Execute the native CI runner contract without waiting on real watchdogs."""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())
STEP = next(step for step in WORKFLOW['jobs']['macos']['steps']
            if step['name'] == 'Run tests')
SCRIPT = STEP['run'].split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]


class CiTestRunnerTests(unittest.TestCase):
    def run_script(self, successful=True, error=None):
        events = []
        suite = object()
        fault = SimpleNamespace(
            enable=lambda: events.append(('enable',)),
            dump_traceback_later=lambda delay, **kwargs: events.append(('timer', delay, kwargs)),
            cancel_dump_traceback_later=lambda: events.append(('cancel',)))

        def discover(path):
            events.append(('discover', path))
            return suite

        def run(actual_suite):
            self.assertIs(actual_suite, suite)
            events.append(('run',))
            if error is not None:
                raise error
            return SimpleNamespace(wasSuccessful=lambda: successful)

        def runner(**kwargs):
            self.assertEqual(kwargs, {'verbosity': 2})
            return SimpleNamespace(run=run)

        tests = SimpleNamespace(defaultTestLoader=SimpleNamespace(discover=discover),
                                TextTestRunner=runner)
        with patch.dict(sys.modules, {'faulthandler': fault, 'unittest': tests}):
            try:
                exec(compile(SCRIPT, 'ci-native-test-runner', 'exec'), {})
            except (SystemExit, RuntimeError) as result:
                return result, events
        self.fail('CI runner must return a test status or propagate the runner error')

    def test_full_suite_has_a_bounded_intel_budget(self):
        result, events = self.run_script()
        self.assertIsInstance(result, SystemExit)
        self.assertEqual(result.code, 0)
        timer = next(event for event in events if event[0] == 'timer')
        self.assertEqual(timer[1], 300)
        self.assertGreaterEqual(STEP['timeout-minutes'] * 60 - timer[1], 60)
        self.assertLessEqual(STEP['timeout-minutes'], 6)
        self.assertEqual(timer[2], {'exit': True})
        self.assertIn(('discover', 'macos/tests'), events)
        self.assertEqual(events[-1], ('cancel',))

    def test_failed_assertions_fail_the_step(self):
        result, events = self.run_script(successful=False)
        self.assertIsInstance(result, SystemExit)
        self.assertEqual(result.code, 1)
        self.assertEqual(events[-1], ('cancel',))

    def test_runner_error_propagates_and_cancels_watchdog(self):
        error = RuntimeError('runner failed')
        result, events = self.run_script(error=error)
        self.assertIs(result, error)
        self.assertEqual(events[-1], ('cancel',))


if __name__ == '__main__':
    unittest.main(verbosity=2)
