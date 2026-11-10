#!/bin/sh
# Local checks (lint + unit tests). Run before pushing: ./check.sh
set -e
cd "$(dirname "$0")"
if command -v ruff >/dev/null 2>&1; then
    ruff check .
else
    echo "ruff not installed: lint skipped" >&2
fi
python3 -I -m unittest discover -s tests -t . -q
