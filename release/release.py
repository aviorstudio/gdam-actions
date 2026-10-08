#!/usr/bin/env python3
"""Publish a same-job verified ZIP without rewriting tags or trusting cached tests."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def main():
    if os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise ValueError('addon releases require main')
    sha = os.environ.get('GITHUB_SHA', '')
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    tag = os.environ.get('GDAM_RELEASE_TAG', '')
    expected = os.environ.get('GDAM_RELEASE_SHA256', '')
    if not re.fullmatch(r'[a-f0-9]{40}', sha) or not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
        raise ValueError('missing immutable caller source identity')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', tag) or not re.fullmatch(r'[a-f0-9]{64}', expected):
        raise ValueError('invalid exact tag or tested artifact digest')
    if not os.environ.get('GH_TOKEN'):
        raise ValueError('GH_TOKEN is required')
    if not os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL') or not os.environ.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN'):
        raise ValueError('registry publication needs the job permission id-token: write')
    root = Path(run('git', 'rev-parse', '--show-toplevel')).resolve()
    if run('git', 'rev-parse', 'HEAD') != sha or run('git', 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('release checkout differs from its verified source')
    if run('gh', 'api', f'repos/{repo}/commits/main', '--jq', '.sha') != sha:
        raise ValueError('main advanced; verify the current source before release')
    existing = subprocess.run(['gh', 'api', f'repos/{repo}/git/ref/tags/{tag}'], capture_output=True, text=True)
    if existing.returncode == 0 or '(HTTP 404)' not in existing.stderr:
        raise ValueError('release tag exists or its absence could not be verified')
    asset = Path(os.environ['GDAM_RELEASE_ASSET'])
    if asset.is_symlink() or not asset.is_file() or not re.fullmatch(r'[@A-Za-z0-9_.-]+\.zip', asset.name) or not asset.resolve().is_relative_to(root):
        raise ValueError('release asset must be a local regular ZIP')
    if hashlib.sha256(asset.read_bytes()).hexdigest() != expected:
        raise ValueError('ZIP differs from the tested artifact')
    with zipfile.ZipFile(asset) as archive:
        names = archive.namelist()
        if not names or len(names) != len({str(PurePosixPath(name)) for name in names}):
            raise ValueError('empty or duplicate ZIP inventory')
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in entry.filename or ':' in entry.filename or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('unsafe ZIP entry')
        if archive.testzip() is not None:
            raise ValueError('corrupt ZIP entry')
    subprocess.run(['gh', 'release', 'create', tag, str(asset), '--repo', repo, '--target', sha,
                    '--title', tag, '--notes', 'Release '+tag], check=True)
    # Recheck bytes after upload and before registry publication. The caller's
    # package verifier owns the closed product-specific inventory.
    if hashlib.sha256(asset.read_bytes()).hexdigest() != expected:
        raise ValueError('ZIP changed during GitHub publication')
    published = json.loads(run('gh', 'api', f'repos/{repo}/releases/tags/{tag}'))
    assets = [entry for entry in published.get('assets', []) if entry.get('name') == asset.name]
    if published.get('tag_name') != tag or len(assets) != 1 or assets[0].get('digest') != 'sha256:'+expected:
        raise ValueError('GitHub release asset differs from the tested ZIP')
    # The registry publication re-reads the release it just created, hashes
    # the uploaded bytes again and attests them with the job's OIDC token.
    environment = {**os.environ, 'GDAM_PUBLISH_TAG': tag, 'GDAM_PUBLISH_ASSET': asset.name}
    subprocess.run(['python3', str(Path(__file__).resolve().parents[1]/'publish/publish.py')], env=environment, check=True)


if __name__ == '__main__':
    main()
