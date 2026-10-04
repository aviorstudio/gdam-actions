import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import textwrap
import unittest

ACTION = Path(__file__).parents[1]/'install/action.yml'

def step(name):
    section = ACTION.read_text().split('- name: '+name, 1)[1].split('    - name:', 1)[0]
    return textwrap.dedent(section.split('      run: |\n', 1)[1])

class InstallerBoundaries(unittest.TestCase):
    def run_fixture(self, corrupt=False, version='v0.0.8', reported='0.0.8'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root/'gdam-reviewed/archive.tar.gz'
            archive.parent.mkdir()
            with tarfile.open(archive, 'w:gz') as bundle:
                body = ('#!/bin/sh\necho gdam '+reported+'\n').encode()
                entry = tarfile.TarInfo('gdam'); entry.mode = 0o755; entry.size = len(body)
                bundle.addfile(entry, io.BytesIO(body))
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            if corrupt: archive.write_bytes(b'corrupt cached archive')
            env = {**os.environ, 'RUNNER_TEMP':directory, 'GDAM_INSTALL_DIR':str(root/'bin'),
                   'GDAM_ARCHIVE_SHA256':checksum, 'GDAM_INSTALL_VERSION':version,
                   'GITHUB_OUTPUT':str(root/'output'), 'GITHUB_PATH':str(root/'path')}
            result = subprocess.run(['bash', '-ec', step('Install GDAM')], env=env, capture_output=True, text=True)
            return result, (root/'bin/gdam').exists(), (root/'output').read_text() if (root/'output').exists() else ''

    def test_reviewed_cache_hit_installs_exact_version(self):
        result, installed, output = self.run_fixture()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(installed); self.assertIn('version=gdam 0.0.8', output)

    def test_corrupt_cache_fails_before_extracting_or_running(self):
        result, installed, output = self.run_fixture(corrupt=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(installed); self.assertEqual(output, '')
        self.assertIn('checksum differs', result.stderr)

    def test_wrong_reviewed_release_cannot_be_reported_as_requested(self):
        result, installed, output = self.run_fixture(reported='0.0.6')
        self.assertNotEqual(result.returncode, 0); self.assertEqual(output, '')

    def test_mutable_versions_or_invalid_hash_fail_preflight(self):
        for version, checksum in [('latest', 'a'*64), ('v0.0.8', 'bad')]:
            env = {**os.environ, 'GDAM_VERSION':version, 'GDAM_SHA256':checksum}
            self.assertNotEqual(subprocess.run(['bash','-ec',step('Validate immutable archive pin')],env=env,capture_output=True).returncode, 0)
