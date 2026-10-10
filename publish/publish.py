#!/usr/bin/env python3
"""Register an existing GitHub Release with the GDAM registry by trusted publishing.

The registry no longer reads GitHub itself. This script reads the release the
caller already created, collects the facts the registry stores (release id,
asset id, name, size, digest, target commit, published time, prerelease) and
posts them with the job's GitHub Actions OIDC token. No GDAM credential exists
any more: the registry trusts the token's repository identity.
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

DEFAULT_API = 'https://api.gdam.dev'
DEFAULT_AUDIENCE = 'api.gdam.dev'
TAG = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
ADDON = re.compile(r'@?([A-Za-z0-9][A-Za-z0-9_.-]*)/([A-Za-z0-9][A-Za-z0-9_.-]*)')
DIGEST = re.compile(r'sha256:([0-9a-f]{64})')
COMMIT = re.compile(r'[0-9a-f]{40}')
DEPENDENCY = re.compile(r'@[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*')
CLASS_NAME = re.compile(r'^\s*class_name\s+([A-Za-z_][A-Za-z0-9_]*)', re.MULTILINE)
ADDON_PATH = re.compile(r'res://addons/(@[^/"\'\s]+)/')


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
    return computed, body


def declaration(body, owner, addon):
    """Read what the asset declares: its root gdam.json dependencies and the
    class_name identifiers its scripts register. The registry stores both and
    refuses a dependency it cannot honour; the lints here fail before any
    token is minted, on the exact bytes that were hashed.

    An addon reaches a dependency only through the .gdam/deps.gd that
    `gdam install` generates, never by a res://addons/... path, because the
    dependency's address differs between a hoisted and a nested install. So a
    reference to another addon's directory is an error, and so is shipping a
    generated .gdam/ directory or a lock in the asset.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile:
        raise PublishError('the release asset is not a zip archive') from None
    entries = [entry.filename.lstrip('/') for entry in archive.infolist() if not entry.is_dir()]
    # gdam installs the archive root, or the single top-level directory
    # when every entry sits under one; mirror that so the lints and the
    # declaration read the files gdam will install.
    tops = {name.split('/', 1)[0] for name in entries}
    prefix = ''
    if len(tops) == 1 and all('/' in name for name in entries):
        prefix = tops.pop() + '/'
    names = [name[len(prefix):] for name in entries if name.startswith(prefix)]
    if 'plugin.cfg' not in names:
        raise PublishError('the release asset has no plugin.cfg at its root')
    for name in names:
        parts = name.split('/')
        if '.gdam' in parts:
            raise PublishError(f'the release asset ships generated content: {name} (exclude .gdam/ when packaging)')
        if parts[-1] == 'gdam.lock':
            raise PublishError(f'the release asset ships a lock file: {name}')
    dependencies = {}
    if 'gdam.json' in names:
        try:
            manifest = json.loads(archive.read(prefix + 'gdam.json').decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as error:
            raise PublishError(f'gdam.json in the release asset is not valid JSON: {error}') from None
        addons = manifest.get('addons') if isinstance(manifest, dict) else None
        if not isinstance(addons, dict) or set(manifest) - {'addons'}:
            raise PublishError('gdam.json in the release asset must hold only an "addons" object')
        for name, entry in addons.items():
            tag = entry.get('tag') if isinstance(entry, dict) else None
            if not DEPENDENCY.fullmatch(name) or set(entry) - {'tag'}:
                raise PublishError(f'gdam.json in the release asset: dependency {name!r} must be "@owner/addon": {{"tag": "<exact tag>"}}')
            if not isinstance(tag, str) or not TAG.fullmatch(tag):
                raise PublishError(f'gdam.json in the release asset: dependency {name} needs an exact tag')
            if name == f'@{owner}/{addon}':
                raise PublishError(f'gdam.json in the release asset: {name} cannot depend on itself')
            dependencies[name] = tag
    classes = []
    self_dir = f'@{owner}_{addon}'
    for name in names:
        if not name.endswith('.gd'):
            continue
        source = archive.read(prefix + name).decode('utf-8', errors='replace')
        for match in CLASS_NAME.finditer(source):
            if match.group(1) not in classes:
                classes.append(match.group(1))
        for directory in sorted(set(ADDON_PATH.findall(source))):
            if directory == self_dir:
                continue
            raise PublishError(f'{name} refers to res://addons/{directory}/ directly; declare the addon in gdam.json '
                               'and reach it through .gdam/deps.gd, which gdam install generates')
    return dependencies, classes


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
    sha256, body_bytes = asset_digest(repository, asset, declared)
    dependencies, classes = declaration(body_bytes, owner, addon)
    del body_bytes
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
        'dependencies': dependencies, 'global_classes': classes,
    }
    editor = os.environ.get('GDAM_EDITOR_PLUGIN', '').strip().lower()
    if editor not in ('', 'false', 'true'):
        raise PublishError(f'editor-plugin must be true or false, got {editor!r}')
    if editor == 'true':
        # Only meaningful when this publish creates the addon; omitted
        # otherwise so the payload stays identical for existing addons.
        body['editor_plugin'] = True
    print(f'Publishing @{owner}/{addon} {tag}: release {body["github_release_id"]}, '
          f'asset {asset["name"]} ({asset["id"]}, {asset["size"]} bytes, sha256:{sha256}), commit {commit}')
    if dependencies:
        print('Declares dependencies: ' + ', '.join(f'{name}@{tag}' for name, tag in sorted(dependencies.items())))
    if classes:
        print('Declares global classes: ' + ', '.join(classes) + ' (this release cannot be a dependency of another addon)')
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
