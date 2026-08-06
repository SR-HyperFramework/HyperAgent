#!/usr/bin/env python3
import argparse
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = "http://192.168.248.169:3000/"


def main() -> int:
    parser = argparse.ArgumentParser(description="HTTP healthcheck")
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="Target URL")
    parser.add_argument("--timeout", type=float, default=5.0, help="Request timeout in seconds")
    args = parser.parse_args()

    started = time.perf_counter()

    try:
        request = urllib.request.Request(args.url, headers={"User-Agent": "hyperagent-healthcheck/1.0"})
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            elapsed_ms = (time.perf_counter() - started) * 1000
            body = response.read(200).decode("utf-8", errors="replace").strip()
            print(f"OK {response.status} {elapsed_ms:.1f}ms {args.url}")
            if body:
                print(body)
            return 0
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"HTTP_ERROR {exc.code} {elapsed_ms:.1f}ms {args.url}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"UNREACHABLE {elapsed_ms:.1f}ms {args.url}: {exc.reason}", file=sys.stderr)
        return 2
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"ERROR {elapsed_ms:.1f}ms {args.url}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
