import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from registry_fixture import Registry, set_release, write_fixture

SCRIPT = Path(__file__).resolve().parents[1] / 'publish/publish.py'
ASSET = b'PK\x03\x04 exact tested bytes'
COMMIT = 'f1cd4bf5e465d40bae2cf432266f9872810e1ce5'


class TrustedPublish(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.registry = Registry()
        self.addCleanup(self.registry.close)
        self.fixture = write_fixture(self.root, ASSET, commit=COMMIT)
        self.output = self.root / 'output'
        self.env = {**os.environ, **self.fixture, **self.registry.environment(),
                    'GITHUB_REPOSITORY': 'aviorstudio/example', 'GITHUB_SHA': COMMIT,
                    'GH_TOKEN': 'fixture-github', 'GDAM_PUBLISH_TAG': 'v1.2.3',
                    'GITHUB_OUTPUT': str(self.output)}
        for key in ('GDAM_PUBLISH_ADDON', 'GDAM_PUBLISH_ASSET', 'GDAM_OIDC_AUDIENCE'):
            self.env.pop(key, None)

    def invoke(self, **overrides):
        env = {**self.env}
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return subprocess.run(['python3', str(SCRIPT)], cwd=self.root, env=env, capture_output=True, text=True)

    def test_posts_release_facts_with_the_oidc_token(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.registry.published(), [{
            'owner': 'aviorstudio', 'addon': 'example', 'tag_name': 'v1.2.3',
            'github_release_id': 406463606, 'commit_sha': COMMIT,
            'asset_id': 620869436, 'asset_name': 'addon.zip',
            'sha256': hashlib.sha256(ASSET).hexdigest(), 'asset_size': len(ASSET),
            'published_at': '2026-10-08T05:47:02Z', 'prerelease': False}])
        token_request = [r for r in self.registry.requests if r[0] == 'GET'][0]
        self.assertEqual(token_request[1], '/token?api-version=2&audience=api.gdam.dev')
        publish = [r for r in self.registry.requests if r[0] == 'POST'][0]
        self.assertEqual(publish[1], '/api/v1/publish')
        self.assertEqual(publish[2]['Authorization'], 'Bearer ' + self.registry.token)
        self.assertNotIn(self.registry.token, result.stdout + result.stderr)
        self.assertNotIn('request-token', result.stdout + result.stderr)
        self.assertIn('Registry answered HTTP 201', result.stdout)
        self.assertIn('created=true\n', self.output.read_text())
        self.assertIn('sha256=' + hashlib.sha256(ASSET).hexdigest() + '\n', self.output.read_text())

    def test_explicit_addon_and_custom_audience(self):
        result = self.invoke(GDAM_PUBLISH_ADDON='@aviorstudio/other-name', GDAM_OIDC_AUDIENCE='registry.example')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.registry.published()[0]['addon'], 'other-name')
        self.assertIn('audience=registry.example', self.registry.requests[0][1])

    def test_idempotent_repeat_is_success(self):
        self.registry.status = 200
        self.registry.response = {'created': False}
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('created=false\n', self.output.read_text())

    def test_registry_rejection_fails_with_body(self):
        for status, message in [(400, 'github_release_id is required'), (403, 'token repository_owner mismatch'),
                                (404, 'unknown handle'), (409, 'tag reuse'), (503, 'the registry database has not been migrated')]:
            with self.subTest(status=status):
                self.registry.status = status
                self.registry.response = {'message': message}
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout)
                self.assertIn(f'HTTP {status}', result.stderr)

    def test_missing_oidc_permission_fails_before_github(self):
        result = self.invoke(ACTIONS_ID_TOKEN_REQUEST_URL=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('id-token: write', result.stderr)
        self.assertEqual(self.registry.requests, [])

    def test_unknown_release_or_asset_never_mints_a_token(self):
        for overrides in [{'GDAM_PUBLISH_TAG': 'v9.9.9'}, {'GDAM_PUBLISH_ASSET': 'missing.zip'}]:
            with self.subTest(overrides=overrides):
                result = self.invoke(**overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.registry.requests, [])

    def test_asset_selection(self):
        other = {'id': 1, 'name': 'other.zip', 'size': 3, 'state': 'uploaded'}
        conventional = {'id': 620869436, 'name': '@aviorstudio_example.gdam.zip', 'size': len(ASSET),
                        'digest': 'sha256:' + hashlib.sha256(ASSET).hexdigest(), 'state': 'uploaded'}
        set_release(self.fixture, assets=[other, conventional])
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.registry.published()[-1]['asset_name'], '@aviorstudio_example.gdam.zip')
        set_release(self.fixture, assets=[other, {**conventional, 'name': 'renamed.zip'}])
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('pass the asset input', result.stderr)
        result = self.invoke(GDAM_PUBLISH_ASSET='renamed.zip')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.registry.published()[-1]['asset_name'], 'renamed.zip')

    def test_digest_and_size_mismatches_fail_closed(self):
        release = json.loads(Path(self.fixture['FAKE_RELEASE']).read_text())
        asset = release['assets'][0]
        for change in [{'digest': 'sha256:' + '0' * 64}, {'size': len(ASSET) + 1}, {'digest': 'md5:abc'},
                       {'state': 'open'}, {'published_at': None}]:
            with self.subTest(change=change):
                if 'published_at' in change:
                    set_release(self.fixture, assets=[asset], published_at=None)
                else:
                    set_release(self.fixture, assets=[{**asset, **change}], published_at=release['published_at'])
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.registry.requests, [])
        set_release(self.fixture, assets=[{k: v for k, v in asset.items() if k != 'digest'}],
                    published_at=release['published_at'])
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.registry.published()[-1]['sha256'], hashlib.sha256(ASSET).hexdigest())

    def test_tag_commit_must_match_the_running_workflow(self):
        result = self.invoke(GITHUB_SHA='b' * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('runs on ' + 'b' * 40, result.stderr)
        self.assertEqual(self.registry.requests, [])
        result = self.invoke(GITHUB_SHA=None)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_malformed_inputs(self):
        for overrides in [{'GDAM_PUBLISH_TAG': ''}, {'GDAM_PUBLISH_TAG': '-bad'}, {'GDAM_PUBLISH_ADDON': 'noslash'},
                          {'GITHUB_REPOSITORY': ''}, {'GDAM_API_URL': 'http://api.gdam.dev'}, {'GH_TOKEN': None}]:
            with self.subTest(overrides=overrides):
                result = self.invoke(**overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.registry.requests, [])


if __name__ == '__main__':
    unittest.main()
