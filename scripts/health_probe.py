"""Small health request worker; its supervisor owns the outer process deadline."""
from __future__ import annotations

import argparse
import json
import math
import os
import threading
from urllib.parse import urlsplit

import requests


def check_health(url: str, timeout_seconds: float) -> dict:
    result = {'healthy': False, 'reason': 'transport_error', 'status': None}
    parsed = urlsplit(url)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        return dict(result, reason='invalid_url')
    try:
        # Keep requests' default certificate verification. Do not follow an
        # authentication/maintenance redirect and mistake it for API readiness.
        with requests.get(url, timeout=(timeout_seconds, timeout_seconds),
                          stream=True, allow_redirects=False) as response:
            result['status'] = response.status_code
            if response.status_code != 200:
                return dict(result, reason='http_status')
            size = 0
            for chunk in response.iter_content(chunk_size=256):
                size += len(chunk)
                if size > 4096:
                    return dict(result, reason='response_too_large')
            return dict(result, healthy=True, reason='healthy')
    except requests.exceptions.SSLError:
        return dict(result, reason='tls_error')
    except requests.exceptions.Timeout:
        return dict(result, reason='deadline_exceeded')
    except Exception:
        # Transport exceptions can contain credentials, proxy URLs, or content.
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--timeout', type=float, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 30:
        return 2
    # Also expire if Task Scheduler kills the supervisor mid-request. A socket
    # read timeout alone cannot stop an indefinitely trickling response body.
    deadline = threading.Timer(args.timeout, lambda: os._exit(124))
    deadline.daemon = True
    deadline.start()
    try:
        result = check_health(args.url, args.timeout)
        print(json.dumps(result, separators=(',', ':')), flush=True)
        return 0 if result['healthy'] else 1
    finally:
        deadline.cancel()


if __name__ == '__main__':
    raise SystemExit(main())
