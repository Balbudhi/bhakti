"""Owner CGI operations. Uses only the configured hostgator SSH alias.

inspect is read-only. provision creates a denied vhost and requests AutoSSL;
activate requires its verified HTTPS certificate. bootstrap writes a setup code
only to an owner-only file outside the repository. No credential goes in argv.
"""
import argparse
from datetime import datetime
import fcntl
import hashlib
import http.client
import json
import os
import re
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile

DOMAIN = 'owner.bhakti.eeshan.xyz'
PUBLIC_NAME = 'bhakti-owner-public'
PRIVATE_NAME = '.bhakti-owner'
MAX_EXPORT = 100 * 1024 * 1024
MAX_GEO = 400 * 1024 * 1024
GEO_MARKER = b'\xab\xcd\xefMaxMind.com'
PUBLIC_ORIGIN = 'https://bhakti.eeshan.xyz'
DENY = r'''# bhakti-owner denied pending HTTPS activation
Options -Indexes -ExecCGI -Includes
RewriteEngine On
RewriteRule ^\.well-known/(acme-challenge/[A-Za-z0-9_-]+|pki-validation/[A-Za-z0-9_-]+\.txt)$ - [END]
RewriteRule ^ - [F,END]
'''
APACHE = r'''# bhakti-owner gateway: never add a static-file bypass.
Options -Indexes -MultiViews -Includes +ExecCGI
DirectoryIndex disabled
LimitRequestBody 524288
<Files "owner.cgi">
    SetHandler cgi-script
</Files>
RewriteEngine On
RewriteCond %{HTTP_HOST} !^owner\.bhakti\.eeshan\.xyz$ [NC]
RewriteRule ^ - [F,END]
RewriteCond %{HTTPS} !=on
RewriteCond %{REQUEST_METHOD} !^(GET|HEAD)$
RewriteRule ^ - [F,END]
RewriteCond %{HTTPS} !=on
RewriteRule ^ https://owner.bhakti.eeshan.xyz%{REQUEST_URI} [R=308,END,NE]
RewriteRule ^\.well-known/(acme-challenge/[A-Za-z0-9_-]+|pki-validation/[A-Za-z0-9_-]+\.txt)$ - [END]
RewriteRule ^owner\.cgi$ - [END]
RewriteRule ^ owner.cgi [END]
Header always set Cache-Control "private, no-store"
Header always set X-Robots-Tag "noindex, nofollow, noarchive"
Header always set X-Content-Type-Options "nosniff"
Header always set Referrer-Policy "no-referrer"
Header always set Strict-Transport-Security "max-age=31536000" "expr=%{HTTPS} == 'on'"
'''


def no_symlinks(path):
    path = Path(path).absolute()
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ValueError('Symlink path refused')
    return Path(os.path.abspath(str(path)))


def overlaps(a, b):
    return a == b or a in b.parents or b in a.parents


def parse_inventory(raw):
    result = raw.get('result', {})
    data = result.get('data', {})
    if result.get('status') != 1 or result.get('errors') or set(data) != {'main_domain', 'sub_domains', 'addon_domains', 'parked_domains'}:
        raise ValueError('Complete successful vhost inventory required')
    if not isinstance(data['main_domain'], dict) or any(not isinstance(data[k], list) for k in ('sub_domains', 'addon_domains', 'parked_domains')):
        raise ValueError('Unexpected vhost inventory')
    entries = [data['main_domain'], *data['sub_domains'], *data['addon_domains']]
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get('domain'), str) or not isinstance(item.get('documentroot'), str) or not Path(item['documentroot']).is_absolute():
            raise ValueError('Incomplete vhost mapping')
    # Parked aliases share main_domain's root. Unknown shapes are not ignored.
    if any(not isinstance(item, (str, dict)) for item in data['parked_domains']):
        raise ValueError('Unexpected parked domain mapping')
    for item in data['parked_domains']:
        if isinstance(item, dict):
            if not item.get('documentroot') or not item.get('domain'):
                raise ValueError('Incomplete parked domain mapping')
            entries.append(item)
    return entries


def check_layout(home, entries):
    home = no_symlinks(home)
    public, private = no_symlinks(home / PUBLIC_NAME), no_symlinks(home / PRIVATE_NAME)
    owner = []
    for entry in entries:
        root = no_symlinks(Path(entry['documentroot']))
        if entry['domain'] == DOMAIN:
            owner.append(entry)
            if root != public:
                raise ValueError('Owner vhost already maps elsewhere')
        elif overlaps(root, public):
            raise ValueError('Public deployment overlaps another vhost')
        if overlaps(root, private):
            raise ValueError('Private state overlaps a vhost')
    if len(owner) > 1:
        raise ValueError('Duplicate owner mapping')
    return public, private


def check_owned_tree(public, private):
    for path in (public, private):
        no_symlinks(path)
        if path.exists() and (not path.is_dir() or path.stat().st_uid != os.getuid()):
            raise ValueError('Unowned deployment directory')
    if private.exists() and stat.S_IMODE(private.stat().st_mode) != 0o700:
        raise ValueError('Private directory must have mode 0700')
    if public.exists():
        allowed = {'.htaccess', 'owner.cgi', '.well-known'}
        if any(child.name not in allowed for child in public.iterdir()):
            raise ValueError('Unexpected public deployment files')
        for child in public.iterdir():
            no_symlinks(child)
            if child.name == '.well-known':
                for nested in child.rglob('*'):
                    no_symlinks(nested)
        ht = public / '.htaccess'
        if ht.exists() and ht.read_text() not in (DENY, APACHE):
            raise ValueError('Unrecognized public protection')
    if private.exists():
        for child in private.iterdir():
            no_symlinks(child)


def destination_path(path, forbidden_roots):
    path = no_symlinks(Path(path).expanduser())
    if any((ancestor / '.git').exists() for ancestor in path.parents):
        raise ValueError('Private output cannot be inside a repository')
    for root in forbidden_roots:
        if path == Path(root).resolve() or Path(root).resolve() in path.parents:
            raise ValueError('Private output cannot be in a repository or public root')
    if path.exists() and (not path.is_file() or path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) != 0o600):
        raise ValueError('Existing private output must be owner-only')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.stat().st_uid != os.getuid() or stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
        raise ValueError('Output directory must be owner-only mode 0700')
    return path


def atomic_file(path, content, mode):
    fd, name = tempfile.mkstemp(prefix='.owner-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as target:
            target.write(content)
            target.flush()
            os.fchmod(target.fileno(), mode)
            os.fsync(target.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_private(path, content, forbidden_roots):
    path = destination_path(path, forbidden_roots)
    atomic_file(path, content, 0o600)


def quiet_command(args):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise ValueError('Hosting command failed; inspect before retrying')
    return result.stdout


def inventory():
    return parse_inventory(json.loads(quiet_command(['uapi', '--output=json', 'DomainInfo', 'domains_data'])))


def remove_generated_cgi_directory(public):
    path = no_symlinks(public / 'cgi-bin')
    if not path.exists():
        return
    if not path.is_dir() or path.stat().st_uid != os.getuid():
        raise ValueError('Unexpected cPanel CGI artifact')
    path.rmdir()  # Only the empty directory just generated by cPanel.


def install_release(public, private, binary, expected):
    if not binary.startswith(b'\x7fELF') or len(binary) > 32 * 1024 * 1024 or hashlib.sha256(binary).hexdigest() != expected:
        raise ValueError('Candidate binary verification failed')
    check_owned_tree(public, private)
    current = public / 'owner.cgi'
    if current.exists() and (public / '.htaccess').read_text() == APACHE:
        atomic_file(private / 'previous.cgi', current.read_bytes(), 0o700)
    atomic_file(public / 'owner.cgi', binary, 0o700)
    atomic_file(public / '.htaccess', APACHE.encode(), 0o644)


def install_geo(private, source, expected):
    """Stream a location database into place; a partial or altered upload changes nothing."""
    fd, name = tempfile.mkstemp(prefix='.owner-', dir=private)
    try:
        digest, size, tail = hashlib.sha256(), 0, b''
        with os.fdopen(fd, 'wb') as target:
            while chunk := source.read(1 << 20):
                size += len(chunk)
                if size > MAX_GEO:
                    raise ValueError('Location database is too large')
                digest.update(chunk)
                tail = (tail + chunk)[-(128 << 10):]  # The format's metadata is at the end.
                target.write(chunk)
            target.flush()
            os.fchmod(target.fileno(), 0o600)
            os.fsync(target.fileno())
        if digest.hexdigest() != expected or GEO_MARKER not in tail:
            raise ValueError('Location database verification failed')
        os.replace(name, private / 'geo.mmdb')
    finally:
        if os.path.exists(name):
            os.unlink(name)


def is_active(public):
    return (public / 'owner.cgi').is_file() and (public / '.htaccess').is_file() and (public / '.htaccess').read_text() == APACHE


def rollback_release(public, private, expected):
    if not expected or hashlib.sha256((public / 'owner.cgi').read_bytes()).hexdigest() != expected:
        raise ValueError('Active binary changed; stale rollback refused')
    previous = private / 'previous.cgi'
    if previous.exists():
        atomic_file(public / 'owner.cgi', previous.read_bytes(), 0o700)
    else:
        atomic_file(public / '.htaccess', DENY.encode(), 0o644)


def remote_main(action, expected=None):
    os.umask(0o077)
    entries = inventory()
    public, private = check_layout(Path.home(), entries)
    check_owned_tree(public, private)
    mapped = any(item['domain'] == DOMAIN for item in entries)
    if action == 'inspect':
        print(json.dumps({'mapped': mapped, 'publicExists': public.exists(), 'privateExists': private.exists(), 'privateDirectory': str(private), 'active': is_active(public), 'sha256': hashlib.sha256((public / 'owner.cgi').read_bytes()).hexdigest() if (public / 'owner.cgi').exists() else None}))
        return
    if action == 'provision':
        if mapped or public.exists() or private.exists():
            raise ValueError('Provision requires absent target; inspect any partial outcome')
        private.mkdir(mode=0o700)
        public.mkdir(mode=0o755)
        atomic_file(public / '.htaccess', DENY.encode(), 0o644)
        response = json.loads(quiet_command(['cpapi2', '--output=json', 'SubDomain', 'addsubdomain', 'domain=owner.bhakti', 'rootdomain=eeshan.xyz', 'dir=' + PUBLIC_NAME, 'disallowdot=0']))
        result = response.get('cpanelresult', {})
        if result.get('event', {}).get('result') != 1 or not result.get('data') or any(item.get('result') != 1 for item in result['data']):
            raise ValueError('Provision outcome requires inspection; root remains denied')
        remove_generated_cgi_directory(public)
        after = inventory()
        check_layout(Path.home(), after)
        if not any(item['domain'] == DOMAIN for item in after):
            raise ValueError('Owner vhost not confirmed; root remains denied')
        ssl = json.loads(quiet_command(['uapi', '--output=json', 'SSL', 'start_autossl_check']))
        if ssl.get('result', {}).get('status') != 1:
            raise ValueError('AutoSSL request unconfirmed; root remains denied')
        print('{"provisioned":true,"denied":true,"certificateRequested":true}')
        return
    if not mapped or not public.exists() or not private.exists():
        raise ValueError('Provisioned owner deployment required')
    lock_path = private / 'deployment.lock'
    no_symlinks(lock_path)
    with lock_path.open('a+b') as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        check_owned_tree(public, private)
        if action == 'activate':
            install_release(public, private, sys.stdin.buffer.read(32 * 1024 * 1024 + 1), expected)
            print(json.dumps({'activated': True, 'sha256': expected}))
        elif action == 'rollback':
            rollback_release(public, private, expected)
            print('{"rolledBack":true}')
        elif action == 'geo':
            install_geo(private, sys.stdin.buffer, expected)
            print(json.dumps({'installed': True, 'sha256': expected}))
        elif action == 'complete':
            data = json.loads(sys.stdin.buffer.read(1025))
            if not isinstance(data, dict) or set(data) != {'requestId', 'expectedTextSha256'}:
                raise ValueError('Invalid completion input')
            validate_completion_identity(data['requestId'], data['expectedTextSha256'])
            output = quiet_command([str(public / 'owner.cgi'), '-state', str(private), '-complete', data['requestId'], '-expected-text-sha256', data['expectedTextSha256']])
            if len(output) > MAX_EXPORT:
                raise ValueError('Unexpected completion output')
            sys.stdout.buffer.write(output)
        elif action in ('bootstrap', 'export'):
            output = quiet_command([str(public / 'owner.cgi'), '-state', str(private), '-init' if action == 'bootstrap' else '-export'])
            if len(output) > (1024 if action == 'bootstrap' else MAX_EXPORT):
                raise ValueError('Unexpected administration output')
            sys.stdout.buffer.write(output)
        else:
            raise ValueError('Unknown remote operation')


def ssh(action, payload=None, expected=None):
    source = Path(__file__).read_text()
    command = ['python3', '-c', source, '--remote', action]
    if expected:
        command += ['--expected', expected]
    result = subprocess.run(['ssh', 'hostgator', shlex.join(command)], input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise ValueError('Remote operation failed; no private diagnostics printed. Inspect before retrying.')
    return result.stdout


def validate_completion_identity(request_id, expected_text_sha256):
    if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', request_id):
        raise ValueError('A canonical request ID is required')
    if not isinstance(expected_text_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_text_sha256):
        raise ValueError('SHA256 of the exact reviewed request text is required')


def complete_request(request_id, expected_text_sha256):
    validate_completion_identity(request_id, expected_text_sha256)
    payload = json.dumps({'requestId': request_id, 'expectedTextSha256': expected_text_sha256}).encode()
    result = json.loads(ssh('complete', payload=payload))
    if not isinstance(result, dict) or result.get('id') != request_id or result.get('status') != 'completed' or not isinstance(result.get('text'), str) or hashlib.sha256(result['text'].encode()).hexdigest() != expected_text_sha256:
        raise ValueError('Completion receipt did not match the reviewed request')
    try:
        completed = datetime.fromisoformat(result['completedAt'].replace('Z', '+00:00'))
        created = datetime.fromisoformat(result['createdAt'].replace('Z', '+00:00'))
        if completed.tzinfo is None or created.tzinfo is None or completed < created:
            raise ValueError('Invalid completion time')
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError('Completion receipt has invalid timestamps') from None
    # Keep the submitted private text out of ordinary command output.
    return {key: result[key] for key in ('id', 'status', 'completedAt')}


def request(path, method='GET', host=DOMAIN, secure=True, body=None, origin=None, content_type='application/json'):
    connection = (http.client.HTTPSConnection if secure else http.client.HTTPConnection)(DOMAIN, timeout=30)
    try:
        headers = {'Host': host, 'User-Agent': 'Bhakti-owner-deployment/1', 'Content-Type': content_type}
        if origin is not None:
            headers['Origin'] = origin
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, dict((key.lower(), value) for key, value in response.getheaders()), response.read(1024 * 1024)
    finally:
        connection.close()


def verify_https(active=False):
    status, headers, body = request('/api/session' if active else '/')
    if not active:
        if status != 403 or 'set-cookie' in headers:
            raise ValueError('Verified HTTPS denied root required before activation')
        return
    if status != 200 or json.loads(body) != {'authenticated': False} or 'no-store' not in headers.get('cache-control', '') or 'application/json' not in headers.get('content-type', '') or 'set-cookie' in headers:
        raise ValueError('Live unauthenticated CGI session contract failed')
    for path in ('/state.json', '/state.lock', '/config.json', '/.htaccess', '/previous.cgi', '/api/requests', '/api/export'):
        code, _, data = request(path)
        if code not in (401, 403, 404) or data.startswith(b'\x7fELF'):
            raise ValueError('Private path was not denied')
    for origin, expected in (('https://' + DOMAIN, 401), ('https://invalid.example', 403)):
        code, returned, data = request('/api/requests', method='POST', body='{}', origin=origin)
        if code != expected or 'set-cookie' in returned or not isinstance(json.loads(data).get('error'), str):
            raise ValueError('Unauthenticated mutation or Origin boundary failed')
    for parameters in ({'path': '/api/requests', 'method': 'POST', 'body': '{}'}, {'path': '/api/session', 'host': 'invalid.example'}, {'path': '/api/auth/begin', 'method': 'POST', 'secure': False, 'body': '{}'}):
        code, returned, _ = request(**parameters)
        if code not in (400, 401, 403, 421) or 'set-cookie' in returned:
            raise ValueError('Transport or authentication boundary failed')
    code, returned, data = request('/owner.cgi')
    if data.startswith(b'\x7fELF') or 'application/octet-stream' in returned.get('content-type', '') or code >= 500:
        raise ValueError('CGI handler not verified')


def verify_visits():
    """Exercise the anonymous boundary; this declared automation is never counted."""
    status, headers, body = request('/api/visit', 'POST', body='{}', origin=PUBLIC_ORIGIN, content_type='text/plain')
    receipt = json.loads(body)
    if status != 200 or set(receipt) != {'day', 'until'} or headers.get('access-control-allow-origin') != PUBLIC_ORIGIN or 'set-cookie' in headers or 'access-control-allow-credentials' in headers:
        raise ValueError('Visitor counting contract failed')
    for parameters in ({'origin': 'https://' + DOMAIN, 'content_type': 'text/plain'}, {'origin': 'https://invalid.example', 'content_type': 'text/plain'}, {'origin': PUBLIC_ORIGIN}):
        status, headers, _ = request('/api/visit', 'POST', body='{}', **parameters)
        if status not in (400, 403) or 'access-control-allow-origin' in headers:
            raise ValueError('Visitor counting boundary failed')
    for path in ('/api/visitors?days=30', '/visits/limiter.json', '/geo.mmdb'):
        if request(path)[0] not in (401, 403, 404):
            raise ValueError('Visitor totals were not private')
    status, headers, body = request('/world.svg')
    if status != 200 or 'image/svg+xml' not in headers.get('content-type', '') or not body.startswith(b'<svg'):
        raise ValueError('Visitor map asset failed')


def local_forbidden_roots():
    roots = [Path(__file__).resolve().parents[2], Path.home() / 'public_html', Path.home() / 'Sites']
    return roots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'provision', 'activate', 'verify', 'rollback', 'bootstrap', 'complete', 'geo'])
    parser.add_argument('--database', type=Path)
    parser.add_argument('--go', default=os.environ.get('GO', 'go'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--request-id')
    parser.add_argument('--expected-text-sha256')
    args = parser.parse_args()
    if args.action == 'inspect':
        result = json.loads(ssh('inspect'))
        result.pop('privateDirectory')
        print(json.dumps(result))
    elif args.action == 'provision':
        print(ssh('provision').decode().strip())
    elif args.action == 'activate':
        info = json.loads(ssh('inspect'))
        verify_https(active=info['active'])
        with tempfile.TemporaryDirectory(prefix='bhakti-owner-build-') as directory:
            output = Path(directory) / 'owner.cgi'
            environment = dict(os.environ, GOOS='linux', GOARCH='amd64', CGO_ENABLED='0')
            result = subprocess.run([args.go, 'build', '-trimpath', '-ldflags', '-s -w -X main.privateDirectory=' + info['privateDirectory'], '-o', str(output), '.'], cwd=Path(__file__).parent, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode:
                raise ValueError('Owner build failed; run local Go tests/build for diagnostics')
            binary = output.read_bytes()
            expected = hashlib.sha256(binary).hexdigest()
            ssh('activate', binary, expected)
            try:
                verify_https(active=True)
                verify_visits()
            except Exception:
                ssh('rollback', expected=expected)
                raise ValueError('Activation verification failed; rollback requested') from None
            print(json.dumps({'active': True, 'httpsVerified': True, 'sha256': expected}))
    elif args.action == 'verify':
        verify_https(active=True)
        verify_visits()
        print('{"httpsVerified":true}')
    elif args.action == 'rollback':
        info = json.loads(ssh('inspect'))
        print(ssh('rollback', expected=info['sha256']).decode().strip())
    elif args.action == 'geo':
        if not args.database or not args.database.is_file() or args.database.stat().st_size > MAX_GEO:
            raise ValueError('geo requires --database with an uncompressed MMDB file')
        data = args.database.read_bytes()
        print(ssh('geo', data, hashlib.sha256(data).hexdigest()).decode().strip())
    elif args.action == 'complete':
        print(json.dumps(complete_request(args.request_id, args.expected_text_sha256)))
    elif args.action == 'bootstrap':
        if not args.output:
            raise ValueError('bootstrap requires --output outside the repository')
        output = destination_path(args.output, local_forbidden_roots())
        verify_https(active=True)
        secret = ssh('bootstrap')
        if not 32 <= len(secret.strip()) <= 256 or len(secret.splitlines()) != 1:
            raise ValueError('Unexpected setup response; nothing printed')
        write_private(output, secret, local_forbidden_roots())
        print('Setup code saved privately; valid for at most 24 hours. Code not printed.')


if __name__ == '__main__':
    try:
        if len(sys.argv) >= 3 and sys.argv[1] == '--remote':
            remote_main(sys.argv[2], sys.argv[4] if len(sys.argv) == 5 and sys.argv[3] == '--expected' else None)
        else:
            main()
    except Exception as error:
        # Remote errors can contain account/home/IP details. Emit neither them nor tracebacks.
        if '--remote' in sys.argv:
            print('Owner hosting operation failed', file=sys.stderr)
        else:
            print(str(error) if isinstance(error, ValueError) else 'Owner operation failed; private diagnostics withheld', file=sys.stderr)
        sys.exit(1)
