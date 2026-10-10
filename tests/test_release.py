import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from registry_fixture import Registry, set_release, write_fixture

SCRIPT = Path(__file__).resolve().parents[1]/'release/release.py'


class TestedRelease(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir='/var/tmp')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root/'source.txt').write_text('verified source\n')
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
        self.sha = subprocess.check_output(['git', '-C', str(self.root), 'rev-parse', 'HEAD'], text=True).strip()
        self.asset = self.root/'addon.zip'
        with zipfile.ZipFile(self.asset, 'w') as archive:
            archive.writestr('addon/plugin.cfg', '[plugin]\nversion="1.2.3"\n')
        self.registry = Registry()
        self.addCleanup(self.registry.close)
        fixture = write_fixture(self.root, self.asset.read_bytes(), commit=self.sha)
        self.log = self.root/'commands.jsonl'
        self.env = {**os.environ, **fixture, **self.registry.environment(), 'GITHUB_REF': 'refs/heads/main',
                    'GITHUB_SHA': self.sha, 'EXPECTED_SHA': self.sha, 'GITHUB_REPOSITORY': 'example/addon',
                    'GDAM_RELEASE_TAG': 'v1.2.3', 'GDAM_RELEASE_ASSET': str(self.asset),
                    'GDAM_RELEASE_SHA256': hashlib.sha256(self.asset.read_bytes()).hexdigest(),
                    'GH_TOKEN': 'fixture-github', 'COMMAND_LOG': str(self.log)}
        self.env.pop('GDAM_API_KEY', None)

    def invoke(self):
        return subprocess.run(['python3', str(SCRIPT)], cwd=self.root, env=self.env, capture_output=True, text=True)

    def test_exact_bytes_github_before_registry(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(commands[0][:4], ['gh', 'release', 'create', 'v1.2.3'])
        self.assertIn(self.sha, commands[0])
        self.assertNotIn(['gdam', 'publish', '@example/addon', 'v1.2.3', 'addon.zip'], commands)
        published = self.registry.published()
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]['owner'], 'example')
        self.assertEqual(published[0]['addon'], 'addon')
        self.assertEqual(published[0]['tag_name'], 'v1.2.3')
        self.assertEqual(published[0]['asset_name'], 'addon.zip')
        self.assertEqual(published[0]['commit_sha'], self.sha)
        self.assertEqual(published[0]['sha256'], self.env['GDAM_RELEASE_SHA256'])
        self.assertNotIn(self.registry.token, result.stdout+result.stderr)

    def test_clerk_key_is_forwarded_without_oidc(self):
        key = 'ak_' + 'A' * 48
        self.env['GDAM_API_KEY'] = key
        self.env.pop('ACTIONS_ID_TOKEN_REQUEST_URL')
        self.env.pop('ACTIONS_ID_TOKEN_REQUEST_TOKEN')
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.registry.requests), 1)
        self.assertEqual(self.registry.requests[0][2]['Authorization'], 'Bearer ' + key)
        self.assertNotIn(key, result.stdout + result.stderr)

    def test_invalid_key_rejects_before_creating_release(self):
        self.env['GDAM_API_KEY'] = 'gdam_sk_old-key'
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())
        self.assertEqual(self.registry.requests, [])

    def test_missing_oidc_permission_rejects_before_github_release(self):
        self.env.pop('ACTIONS_ID_TOKEN_REQUEST_URL')
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('id-token: write', result.stderr)
        self.assertFalse(self.log.exists())

    def test_changed_source_digest_ref_and_existing_tag_reject_before_publication(self):
        for key, value in [('GITHUB_REF','refs/heads/feature'), ('GITHUB_SHA','a'*40),
                           ('GDAM_RELEASE_SHA256','0'*64), ('EXPECTED_SHA','b'*40), ('EXISTING_TAG','1')]:
            with self.subTest(key=key):
                previous = self.env.get(key)
                self.env[key] = value
                self.assertNotEqual(self.invoke().returncode, 0)
                self.assertFalse(self.log.exists())
                if previous is None:self.env.pop(key)
                else:self.env[key] = previous

    def test_zip_traversal_rejected(self):
        with zipfile.ZipFile(self.asset, 'w') as archive:archive.writestr('../escape', 'bad')
        self.env['GDAM_RELEASE_SHA256'] = hashlib.sha256(self.asset.read_bytes()).hexdigest()
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertFalse(self.log.exists())

    def test_remote_asset_mismatch_never_reaches_registry(self):
        set_release(self.env, assets=[{'id': 1, 'name': 'addon.zip', 'size': 3, 'digest': 'sha256:'+'0'*64}])
        self.assertNotEqual(self.invoke().returncode, 0)
        commands = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(commands[0][:3], ['gh','release','create'])
        self.assertEqual(self.registry.requests, [])
