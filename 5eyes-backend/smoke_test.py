from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


DEFAULT_BASE_URL = f"http://{os.getenv('APP_HOST', '127.0.0.1')}:{os.getenv('APP_PORT', '8000')}"


def http_json(method: str, url: str, payload: dict | None = None, token: str | None = None):
    data = None
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode('utf-8')
        content_type = resp.headers.get('Content-Type', '')
        return json.loads(body) if 'application/json' in content_type else body


def main() -> int:
    parser = argparse.ArgumentParser(description='Quick smoke test for the 5Eyes backend.')
    parser.add_argument('--base-url', default=DEFAULT_BASE_URL)
    parser.add_argument('--username', required=True)
    parser.add_argument('--password', required=True)
    args = parser.parse_args()

    base = args.base_url.rstrip('/')
    try:
        root = http_json('GET', f'{base}/')
        ready = http_json('GET', f'{base}/health/ready')
        login = http_json('POST', f'{base}/auth/login', {
            'username': args.username,
            'password': args.password,
        })
        token = login['access_token']
        me = http_json('GET', f'{base}/auth/me', token=token)
        clients = http_json('GET', f'{base}/clients', token=token)
        price_status = http_json('GET', f'{base}/admin/prices/status', token=token)

        print('Smoke test erfolgreich')
        print(json.dumps({
            'root': root,
            'ready': ready,
            'me': me,
            'client_count': len(clients) if isinstance(clients, list) else 'n/a',
            'price_status': price_status,
        }, ensure_ascii=False, indent=2))
        return 0
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode('utf-8', errors='replace')
        print(f'HTTPError {exc.code}: {payload}', file=sys.stderr)
        return 1
    except Exception as exc:
        print(f'Smoke test fehlgeschlagen: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
