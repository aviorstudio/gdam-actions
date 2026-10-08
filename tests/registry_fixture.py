"""Loopback stand-ins for GitHub (a fake `gh`) and the GDAM registry."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import threading

FAKE_GH = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
# Only mutating commands are logged: a test asserts "nothing was created" by
# the log's absence.
if args[0] == 'release':
    assert args[1] == 'create', args
    with Path(os.environ['COMMAND_LOG']).open('a') as out: out.write(json.dumps(['gh']+args)+'\\n')
    sys.exit(0)
assert args[0] == 'api', args
release = json.loads(Path(os.environ['FAKE_RELEASE']).read_text())
asset_bytes = Path(os.environ['FAKE_ASSET']).read_bytes()
if '-H' in args:
    path = args[3]
    assert args[2] == 'Accept: application/octet-stream'
    assert any(path.endswith('/releases/assets/'+str(a['id'])) for a in release['assets']), path
    sys.stdout.buffer.write(asset_bytes); sys.exit(0)
path = args[1]
if '/releases/tags/' in path:
    tag = path.rsplit('/', 1)[1]
    if tag != release['tag_name']:
        print('gh: Not Found (HTTP 404)', file=sys.stderr); sys.exit(1)
    print(json.dumps(release)); sys.exit(0)
if path.endswith('/commits/main'):
    print(os.environ['EXPECTED_SHA']); sys.exit(0)
if '/commits/' in path:
    print(os.environ['FAKE_TAG_COMMIT']); sys.exit(0)
if '/git/ref/' in path:
    if os.environ.get('EXISTING_TAG'): print('{}'); sys.exit(0)
    print('gh: Not Found (HTTP 404)', file=sys.stderr); sys.exit(1)
print('unexpected gh api path '+path, file=sys.stderr); sys.exit(1)
'''


class Registry:
    """Serves the OIDC token endpoint and POST /api/v1/publish on loopback."""

    def __init__(self, status=201, response=None, token='eyJhbGciOiJSUzI1NiJ9.eyJhdWQiOiJhcGkuZ2RhbS5kZXYifQ.sig'):
        self.requests = []
        self.status = status
        self.response = response if response is not None else {'created': status == 201, 'tag_name': 'v1.2.3'}
        self.token = token
        fixture = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                fixture.requests.append(('GET', self.path, dict(self.headers), b''))
                if self.headers.get('Authorization') != 'bearer request-token-' + fixture.token[-3:]:
                    self.send_response(401); self.end_headers(); return
                body = json.dumps({'value': fixture.token}).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get('Content-Length', '0'))
                body = self.rfile.read(length)
                fixture.requests.append(('POST', self.path, dict(self.headers), body))
                payload = json.dumps(fixture.response).encode()
                self.send_response(fixture.status); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload))); self.end_headers(); self.wfile.write(payload)

        self.server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.server_address[1]}'

    def environment(self):
        return {'GDAM_API_URL': self.url, 'ACTIONS_ID_TOKEN_REQUEST_URL': self.url + '/token?api-version=2',
                'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'request-token-' + self.token[-3:]}

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def published(self):
        return [json.loads(body) for method, path, _, body in self.requests if method == 'POST']


def write_fixture(root, asset_bytes, tag='v1.2.3', name='addon.zip', commit='a' * 40, digest=True):
    """Materialise the fake `gh`, a release document and the asset bytes under root."""
    binary = root / 'bin'
    binary.mkdir(exist_ok=True)
    gh = binary / 'gh'
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    asset = root / 'asset.bin'
    asset.write_bytes(asset_bytes)
    entry = {'id': 620869436, 'name': name, 'size': len(asset_bytes), 'state': 'uploaded'}
    if digest:
        entry['digest'] = 'sha256:' + hashlib.sha256(asset_bytes).hexdigest()
    release = {'id': 406463606, 'tag_name': tag, 'published_at': '2026-10-08T05:47:02Z',
               'prerelease': False, 'assets': [entry]}
    document = root / 'release.json'
    document.write_text(json.dumps(release))
    return {'PATH': str(binary) + ':' + os.environ['PATH'], 'FAKE_RELEASE': str(document),
            'FAKE_ASSET': str(asset), 'FAKE_TAG_COMMIT': commit}


def set_release(env, **changes):
    document = Path(env['FAKE_RELEASE'])
    release = json.loads(document.read_text())
    assets = changes.pop('assets', None)
    release.update(changes)
    if assets is not None:
        release['assets'] = assets
    document.write_text(json.dumps(release))
    return release
