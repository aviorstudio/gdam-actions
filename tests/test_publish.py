import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from registry_fixture import Registry, set_release, write_fixture

SCRIPT = Path(__file__).resolve().parents[1] / 'publish/publish.py'
COMMIT = 'f1cd4bf5e465d40bae2cf432266f9872810e1ce5'


def asset_zip(files=None):
    """A release asset: plugin.cfg at the root plus the given files, as exact bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('plugin.cfg', '[plugin]\nname="Example"\n')
        for name, body in (files or {}).items():
            archive.writestr(name, body)
    return buffer.getvalue()


ASSET = asset_zip()


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
        for key in ('GDAM_PUBLISH_ADDON', 'GDAM_PUBLISH_ASSET', 'GDAM_OIDC_AUDIENCE', 'GDAM_EDITOR_PLUGIN'):
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

    def test_editor_plugin_is_sent_only_when_set(self):
        for value, expected in [('true', True), ('false', None), ('', None)]:
            with self.subTest(value=value):
                result = self.invoke(GDAM_EDITOR_PLUGIN=value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.registry.published()[-1].get('editor_plugin'), expected)
        result = self.invoke(GDAM_EDITOR_PLUGIN='yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.registry.published()), 3)

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


    def republish(self, files, **overrides):
        """Swap the fixture's asset for one with these files and publish."""
        body = asset_zip(files)
        Path(self.fixture['FAKE_ASSET']).write_bytes(body)
        release = json.loads(Path(self.fixture['FAKE_RELEASE']).read_text())
        asset = {**release['assets'][0], 'size': len(body), 'digest': 'sha256:' + hashlib.sha256(body).hexdigest()}
        set_release(self.fixture, assets=[asset])
        return self.invoke(**overrides)

    def test_declaration_is_read_from_the_hashed_asset(self):
        result = self.republish({
            'gdam.json': json.dumps({'addons': {'@aviorstudio/gd-session': {'tag': 'v0.0.1'}}}),
            'src/clerk.gd': 'class_name GdClerk\nextends RefCounted\nconst Deps = preload("../.gdam/deps.gd")\n',
            'src/self.gd': 'const Own = preload("res://addons/@aviorstudio_example/src/clerk.gd")\n',
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        published = self.registry.published()[-1]
        self.assertEqual(published['dependencies'], {'@aviorstudio/gd-session': 'v0.0.1'})
        self.assertEqual(published['global_classes'], ['GdClerk'])
        # Only what is declared is sent: a class-free asset with dependencies omits global_classes.
        result = self.republish({'gdam.json': json.dumps({'addons': {'@aviorstudio/gd-session': {'tag': 'v0.0.1'}}})})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('global_classes', self.registry.published()[-1])
        self.assertIn('Declares dependencies: @aviorstudio/gd-session@v0.0.1', result.stdout)
        self.assertIn('Declares global classes: GdClerk', result.stdout)

    def test_declaration_lints_fail_before_any_token(self):
        cases = [
            ({'src/a.gd': 'const X = preload("res://addons/@aviorstudio_gd-session/src/x.gd")\n'}, 'reach it through .gdam/deps.gd'),
            ({'.gdam/deps.gd': '# generated\n'}, 'ships generated content'),
            ({'gdam.lock': '{}'}, 'ships a lock file'),
            ({'gdam.json': '{"addons": {"gd-session": {"tag": "v1"}}}'}, 'must be "@owner/addon"'),
            ({'gdam.json': '{"addons": {"@aviorstudio/gd-session": {"tag": ""}}}'}, 'needs an exact tag'),
            ({'gdam.json': '{"addons": {"@aviorstudio/example": {"tag": "v1"}}}'}, 'cannot depend on itself'),
            ({'gdam.json': '{"addons": {}, "package": "addon"}'}, 'must hold only an "addons" object'),
            ({'gdam.json': 'not json'}, 'not valid JSON'),
        ]
        for files, message in cases:
            with self.subTest(message=message):
                before = len(self.registry.requests)
                result = self.republish(files)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(message, result.stderr)
                self.assertEqual(len(self.registry.requests), before, 'a lint failure must not mint a token')

    def test_asset_must_be_a_zip_with_plugin_cfg(self):
        Path(self.fixture['FAKE_ASSET']).write_bytes(b'not a zip')
        release = json.loads(Path(self.fixture['FAKE_RELEASE']).read_text())
        asset = {**release['assets'][0], 'size': 9, 'digest': 'sha256:' + hashlib.sha256(b'not a zip').hexdigest()}
        set_release(self.fixture, assets=[asset])
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not a zip archive', result.stderr)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('src/only.gd', 'extends Node\n')
        Path(self.fixture['FAKE_ASSET']).write_bytes(buffer.getvalue())
        set_release(self.fixture, assets=[{**asset, 'size': len(buffer.getvalue()), 'digest': 'sha256:' + hashlib.sha256(buffer.getvalue()).hexdigest()}])
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no plugin.cfg at its root', result.stderr)
        self.assertEqual(self.registry.requests, [])


if __name__ == '__main__':
    unittest.main()
