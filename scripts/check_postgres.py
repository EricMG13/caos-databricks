"""Fail safely unless the configured test PostgreSQL accepts a connection."""

from __future__ import annotations

import os

import psycopg


def main() -> int:
    url = os.environ.get("CAOS_TEST_POSTGRES_URL")
    if not url:
        print("CAOS_TEST_POSTGRES_URL is required")
        return 1
    try:
        with psycopg.connect(url, connect_timeout=2):
            return 0
    except psycopg.Error:
        print("test PostgreSQL is not reachable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
