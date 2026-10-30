"""Bounded operator-invoked health load probe; no credentials or paid AI calls."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import time
from urllib.parse import urlsplit
import httpx


def run(base_url, requests=50, workers=4, transport=None):
    parsed = urlsplit(base_url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment):
        raise ValueError('Provide an HTTP(S) origin without credentials or path')
    if not 1 <= requests <= 1000 or not 1 <= workers <= 16:
        raise ValueError('Requests must be 1..1000 and workers 1..16')
    def probe(_index):
        started = time.monotonic()
        try:
            with httpx.Client(timeout=5, trust_env=False, follow_redirects=False, transport=transport) as client:
                response = client.get(base_url.rstrip('/') + '/api/health')
            ok = response.status_code == 200
        except httpx.HTTPError:
            ok = False
        return ok, (time.monotonic() - started) * 1000
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(probe, range(requests)))
    elapsed = time.monotonic() - started
    durations = sorted(row[1] for row in results)
    return {'scope': 'unauthenticated health endpoint only; not an AI throughput benchmark',
            'requests': requests, 'workers': workers,
            'successful': sum(row[0] for row in results),
            'failed': sum(not row[0] for row in results),
            'p95_ms': round(durations[math.ceil(len(durations) * .95) - 1], 2),
            'requests_per_second': round(requests / max(elapsed, .001), 2)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    parser.add_argument('--requests', type=int, default=50)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    result = run(args.base_url, args.requests, args.workers)
    print(json.dumps(result, indent=2))
    return 1 if result['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
