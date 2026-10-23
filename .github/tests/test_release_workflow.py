"""Exercise publication failure and retry behavior with a local GitHub CLI double."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())
RELEASE = WORKFLOW['jobs']['release']
SCRIPT = RELEASE['steps'][-1]['run']
SHA = 'a' * 40
OTHER = 'b' * 40
FAKE_GH = '''#!PYTHON
import json, os, pathlib, sys
args = sys.argv[1:]
root = pathlib.Path(os.environ['FAKE_ROOT'])
case = json.loads((root / 'case.json').read_text())
with (root / 'calls.jsonl').open('a') as log:
    log.write(json.dumps(args) + '\\n')
if args[:2] == ['release', 'create']:
    if case.get('create_failure'): sys.exit(1)
    (root / 'created').write_text('yes')
    print('https://github.com/example/project/releases/tag/build-4')
elif args[:2] == ['release', 'upload']:
    if case.get('upload_failure'): sys.exit(1)
    expected = {f'artifacts/FMSeasonHub-macos-{arch}.{suffix}'
                for arch in ('arm64', 'x86_64') for suffix in ('dmg', 'dmg.sha256', 'json')}
    if set(args[4:]) != expected: raise SystemExit('Expected both DMG installers, checksums and metadata')
elif args[:2] == ['release', 'edit']:
    if case.get('publish_failure'): sys.exit(1)
    print('PUBLISHED')
elif args[0] == 'api':
    endpoint = args[1]
    if endpoint.endswith('/git/ref/heads/main'):
        if case.get('main_failure'): sys.exit(1)
        print(case.get('main', os.environ['RELEASE_SHA']))
    elif '/git/matching-refs/' in endpoint:
        if case.get('tag'): print('refs/tags/build-4')
    elif '/commits/' in endpoint:
        print(case.get('tag_sha', os.environ['RELEASE_SHA']))
    elif '/releases?' in endpoint:
        if case.get('list_failure'): sys.exit(1)
        if case.get('state'):
            draft = 'true' if case['state'] == 'draft' else 'false'
            prerelease = 'true' if case.get('prerelease') else 'false'
            print('\\t'.join([draft, prerelease, case.get('target', os.environ['RELEASE_SHA'])]))
    elif '/releases/tags/' in endpoint:
        print(case.get('asset_count', 6))
    else: raise SystemExit('Unexpected endpoint: ' + endpoint)
else: raise SystemExit('Unexpected args: ' + repr(args))
'''.replace('PYTHON', sys.executable, 1)


class ReleaseWorkflowTests(unittest.TestCase):
    def run_case(self, case):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'gh').write_text(FAKE_GH)
            (root / 'gh').chmod(0o755)
            (root / 'case.json').write_text(json.dumps(case))
            script = root / 'release.sh'
            script.write_text(SCRIPT)
            env = dict(os.environ, PATH=f'{root}:/usr/bin:/bin',
                       GH_TOKEN='test-only', GH_REPO='example/project',
                       RELEASE_SHA=SHA, RELEASE_TAG='build-4',
                       RUNNER_TEMP=folder, FAKE_ROOT=folder,
                       GITHUB_STEP_SUMMARY=str(root / 'summary'),
                       GITHUB_SERVER_URL='https://github.com', GITHUB_RUN_ID='123')
            result = subprocess.run(['bash', str(script)], env=env,
                                    capture_output=True, text=True, timeout=10)
            calls = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
            creates = [call for call in calls if call[:2] == ['release', 'create']]
            notes = (root / 'release-notes.md').read_text() if (root / 'release-notes.md').exists() else ''
            return result, creates, notes

    def test_release_is_gated_and_token_is_scoped(self):
        self.assertEqual(RELEASE['needs'], 'macos')
        self.assertEqual(RELEASE['if'], "github.event_name == 'push' && github.ref == 'refs/heads/main'")
        self.assertEqual(WORKFLOW['permissions'], {'contents': 'read'})
        self.assertEqual(RELEASE['permissions'], {'contents': 'write'})

    def test_fresh_release_targets_exact_commit(self):
        result, creates, notes = self.run_case({})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0][creates[0].index('--target') + 1], SHA)
        self.assertIn('--generate-notes', creates[0])
        self.assertIn('Python and dependencies are included', notes)
        self.assertIn('FMSeasonHub-macos-arm64.dmg', notes)
        self.assertIn('FMSeasonHub-macos-x86_64.dmg', notes)
        self.assertIn('Eject the DMG', notes)
        self.assertIn("A DMG does not remove Apple's security warning", notes)
        self.assertIn(f'/blob/{SHA}/macos/README.md', notes)

    def test_existing_success_is_not_republished(self):
        result, creates, _ = self.run_case({'tag': True, 'state': 'published'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(creates, [])

    def test_tag_only_retry_creates_release(self):
        result, creates, _ = self.run_case({'tag': True})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(creates), 1)

    def test_published_release_requires_its_tag(self):
        result, creates, _ = self.run_case({'state': 'published'})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(creates, [])

    def test_older_commit_is_not_published(self):
        result, creates, _ = self.run_case({'main': OTHER})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(creates, [])

    def test_wrong_tag_is_rejected(self):
        result, creates, _ = self.run_case({'tag': True, 'tag_sha': OTHER})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(creates, [])

    def test_partial_draft_can_resume(self):
        result, creates, _ = self.run_case({'state': 'draft'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(creates, [])
        self.assertIn('PUBLISHED', result.stdout)

    def test_wrong_draft_target_is_rejected(self):
        result, creates, _ = self.run_case({'state': 'draft', 'target': OTHER})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(creates, [])
        self.assertNotIn('PUBLISHED', result.stdout)

    def test_failed_upload_does_not_publish(self):
        result, creates, _ = self.run_case({'upload_failure': True})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('PUBLISHED', result.stdout)

    def test_published_release_requires_all_assets(self):
        result, creates, _ = self.run_case({'tag': True, 'state': 'published', 'asset_count': 1})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(creates, [])

    def test_api_errors_do_not_trigger_publication(self):
        for field in ['main_failure', 'list_failure']:
            with self.subTest(field=field):
                result, creates, _ = self.run_case({field: True})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(creates, [])

    def test_create_error_fails_job(self):
        result, creates, _ = self.run_case({'create_failure': True})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(creates), 1)

    def test_post_publish_tag_mismatch_fails_job(self):
        result, creates, _ = self.run_case({'tag_sha': OTHER})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(creates), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
