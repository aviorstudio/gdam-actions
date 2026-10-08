#!/usr/bin/env python3
"""Register an existing GitHub Release with the GDAM registry by trusted publishing.

The registry no longer reads GitHub itself. This script reads the release the
caller already created, collects the facts the registry stores (release id,
asset id, name, size, digest, target commit, published time, prerelease) and
posts them with the job's GitHub Actions OIDC token. No GDAM credential exists
any more: the registry trusts the token's repository identity.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API = 'https://api.gdam.dev'
DEFAULT_AUDIENCE = 'api.gdam.dev'
TAG = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
ADDON = re.compile(r'@?([A-Za-z0-9][A-Za-z0-9_.-]*)/([A-Za-z0-9][A-Za-z0-9_.-]*)')
DIGEST = re.compile(r'sha256:([0-9a-f]{64})')
COMMIT = re.compile(r'[0-9a-f]{40}')


class PublishError(Exception):
    pass


def gh(*args, binary=False):
    try:
        return subprocess.run(['gh', *args], check=True, capture_output=True, text=not binary).stdout
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors='replace') if binary else error.stderr
        raise PublishError(f'gh {args[0]} {args[1]} failed: {detail.strip()}') from None


def release_facts(repository, tag, asset_name, conventional):
    release = json.loads(gh('api', f'repos/{repository}/releases/tags/{tag}'))
    if release.get('tag_name') != tag or not isinstance(release.get('id'), int):
        raise PublishError(f'GitHub returned a different release for tag {tag}')
    assets = release.get('assets') or []
    names = [entry.get('name') for entry in assets]
    if asset_name:
        chosen = [entry for entry in assets if entry.get('name') == asset_name]
        if len(chosen) != 1:
            raise PublishError(f'release {tag} has no asset named {asset_name}; assets: {names}')
    elif len(assets) == 1:
        chosen = assets
    else:
        chosen = [entry for entry in assets if entry.get('name') == conventional]
        if len(chosen) != 1:
            raise PublishError(f'release {tag} has {len(assets)} assets and none named {conventional}; '
                               f'pass the asset input; assets: {names}')
    asset = chosen[0]
    if not isinstance(asset.get('id'), int) or not isinstance(asset.get('size'), int):
        raise PublishError('GitHub asset lacks a numeric id or size')
    if asset.get('state') not in (None, 'uploaded'):
        raise PublishError(f'asset {asset["name"]} is not uploaded yet (state {asset.get("state")})')
    declared = asset.get('digest')
    if declared is not None and not DIGEST.fullmatch(str(declared)):
        raise PublishError(f'GitHub asset digest has an unexpected format: {declared}')
    published_at = release.get('published_at')
    if not isinstance(published_at, str) or not published_at:
        raise PublishError('release has no published_at; drafts cannot be published to GDAM')
    return release, asset, declared


def asset_digest(repository, asset, declared):
    # Hash the bytes consumers will download rather than trusting a field. If
    # GitHub also declares a digest, the two must agree.
    body = gh('api', '-H', 'Accept: application/octet-stream',
              f'repos/{repository}/releases/assets/{asset["id"]}', binary=True)
    if len(body) != asset['size']:
        raise PublishError(f'downloaded {len(body)} bytes but GitHub declares size {asset["size"]}')
    computed = hashlib.sha256(body).hexdigest()
    if declared is not None and DIGEST.fullmatch(declared).group(1) != computed:
        raise PublishError(f'GitHub declares digest {declared} but the asset bytes hash to sha256:{computed}')
    return computed


def tag_commit(repository, tag):
    commit = gh('api', f'repos/{repository}/commits/{tag}', '--jq', '.sha').strip()
    if not COMMIT.fullmatch(commit):
        raise PublishError(f'could not resolve tag {tag} to a commit: {commit!r}')
    return commit


def http(method, url, headers, data=None):
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode('utf-8', errors='replace')
    except urllib.error.URLError as error:
        raise PublishError(f'{method} {url}: {error.reason}') from None


def oidc_token(audience):
    url = os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL', '')
    bearer = os.environ.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN', '')
    if not url or not bearer:
        raise PublishError('no GitHub Actions OIDC token is available: the job needs '
                           '`permissions: id-token: write` (and contents: read)')
    joined = url + ('&' if '?' in url else '?') + urllib.parse.urlencode({'audience': audience})
    status, body = http('GET', joined, {'Authorization': f'bearer {bearer}', 'Accept': 'application/json'})
    if status != 200:
        raise PublishError(f'OIDC token request failed with HTTP {status}')
    try:
        value = json.loads(body).get('value')
    except ValueError:
        value = None
    if not isinstance(value, str) or value.count('.') != 2:
        raise PublishError('OIDC token response did not contain a JWT')
    return value


def main():
    tag = os.environ.get('GDAM_PUBLISH_TAG', '')
    repository = os.environ.get('GITHUB_REPOSITORY', '')
    spec = os.environ.get('GDAM_PUBLISH_ADDON', '') or ('@' + repository if repository else '')
    api = (os.environ.get('GDAM_API_URL', '') or DEFAULT_API).rstrip('/')
    audience = os.environ.get('GDAM_OIDC_AUDIENCE', '') or DEFAULT_AUDIENCE
    if not TAG.fullmatch(tag):
        raise PublishError('missing or malformed exact GitHub Release tag')
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository):
        raise PublishError('GITHUB_REPOSITORY is not set; this action runs inside GitHub Actions')
    match = ADDON.fullmatch(spec)
    if not match:
        raise PublishError(f'addon must look like @owner/addon, got {spec!r}')
    owner, addon = match.groups()
    if not api.startswith('https://') and not api.startswith('http://127.0.0.1') and not api.startswith('http://localhost'):
        raise PublishError('api-url must be https')
    if not os.environ.get('GH_TOKEN') and not os.environ.get('GITHUB_TOKEN'):
        raise PublishError('GH_TOKEN is required to read the GitHub release')
    # Check the token plumbing before touching GitHub so a missing permission
    # reads as what it is rather than as a registry rejection later.
    if not os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL') or not os.environ.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN'):
        raise PublishError('no GitHub Actions OIDC token is available: the job needs '
                           '`permissions: id-token: write` (and contents: read)')

    conventional = f'@{owner}_{addon}.gdam.zip'
    release, asset, declared = release_facts(repository, tag, os.environ.get('GDAM_PUBLISH_ASSET', ''), conventional)
    sha256 = asset_digest(repository, asset, declared)
    commit = tag_commit(repository, tag)
    run_sha = os.environ.get('GITHUB_SHA', '')
    if run_sha and run_sha != commit:
        raise PublishError(f'tag {tag} points at {commit} but this workflow runs on {run_sha}; '
                           'the registry only accepts a release of the commit the publishing workflow checked out')
    body = {
        'owner': owner, 'addon': addon, 'tag_name': tag,
        'github_release_id': release['id'], 'commit_sha': commit,
        'asset_id': asset['id'], 'asset_name': asset['name'], 'sha256': sha256,
        'asset_size': asset['size'], 'published_at': release['published_at'],
        'prerelease': bool(release.get('prerelease', False)),
    }
    print(f'Publishing @{owner}/{addon} {tag}: release {body["github_release_id"]}, '
          f'asset {asset["name"]} ({asset["id"]}, {asset["size"]} bytes, sha256:{sha256}), commit {commit}')
    token = oidc_token(audience)
    status, text = http('POST', api + '/api/v1/publish',
                        {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
                         'Accept': 'application/json'},
                        json.dumps(body).encode())
    del token
    print(f'Registry answered HTTP {status}: {text}')
    if status not in (200, 201):
        raise PublishError(f'registry rejected the publication with HTTP {status}')
    try:
        created = json.loads(text).get('created')
    except ValueError:
        created = None
    print('Created' if created else 'Already recorded with identical facts' if created is False else 'Accepted')
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as handle:
            handle.write(f'created={"true" if created else "false"}\n')
            handle.write(f'sha256={sha256}\n')


if __name__ == '__main__':
    try:
        main()
    except PublishError as error:
        print(f'::error::{error}', file=sys.stderr)
        sys.exit(1)
