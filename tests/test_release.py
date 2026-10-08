import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

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
        binary = self.root/'bin'
        binary.mkdir()
        gh = binary/'gh'
        gh.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
if sys.argv[1]=='api':
 if '/releases/tags/' in sys.argv[2]:
  print(json.dumps({'tag_name':os.environ['GDAM_RELEASE_TAG'],'assets':[{'name':'addon.zip','digest':'sha256:'+os.environ.get('REMOTE_DIGEST',os.environ['GDAM_RELEASE_SHA256'])}]}));sys.exit(0)
 if '/git/ref/' in sys.argv[2]:
  if os.environ.get('EXISTING_TAG'): print('{}');sys.exit(0)
  print('gh: Not Found (HTTP 404)',file=sys.stderr);sys.exit(1)
 print(os.environ['EXPECTED_SHA']);sys.exit(0)
with Path(os.environ['COMMAND_LOG']).open('a') as out:out.write(json.dumps(['gh']+sys.argv[1:])+'\\n')
''')
        cli = binary/'gdam'
        cli.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
if len(sys.argv)==2:
 assert 'GDAM_SECRET_KEY' not in os.environ
 assert 'GH_TOKEN' not in os.environ
 print('usage: gdam publish @username/addon TAG [ASSET_NAME]');sys.exit(2)
assert 'GH_TOKEN' not in os.environ
with Path(os.environ['COMMAND_LOG']).open('a') as out:out.write(json.dumps(['gdam']+sys.argv[1:])+'\\n')
''')
        gh.chmod(0o755)
        cli.chmod(0o755)
        self.log = self.root/'commands.jsonl'
        self.env = {**os.environ, 'PATH': str(binary)+':'+os.environ['PATH'], 'GITHUB_REF': 'refs/heads/main',
                    'GITHUB_SHA': self.sha, 'EXPECTED_SHA': self.sha, 'GITHUB_REPOSITORY': 'example/addon',
                    'GDAM_RELEASE_TAG': 'v1.2.3', 'GDAM_RELEASE_ASSET': str(self.asset),
                    'GDAM_RELEASE_SHA256': hashlib.sha256(self.asset.read_bytes()).hexdigest(),
                    'GH_TOKEN': 'fixture-github', 'GDAM_SECRET_KEY': 'fixture-registry', 'COMMAND_LOG': str(self.log)}

    def invoke(self):
        return subprocess.run(['python3', str(SCRIPT)], cwd=self.root, env=self.env, capture_output=True, text=True)

    def test_exact_bytes_github_before_registry(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(commands[0][:4], ['gh', 'release', 'create', 'v1.2.3'])
        self.assertIn(self.sha, commands[0])
        self.assertEqual(commands[1], ['gdam', 'publish', '@example/addon', 'v1.2.3', 'addon.zip'])
        self.assertNotIn('fixture-registry', result.stdout+result.stderr)

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
        self.env['REMOTE_DIGEST'] = '0'*64
        self.assertNotEqual(self.invoke().returncode, 0)
        commands = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][:3], ['gh','release','create'])
