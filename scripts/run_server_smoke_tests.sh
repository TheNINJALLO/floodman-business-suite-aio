#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/server/office-console${PYTHONPATH:+:$PYTHONPATH}"
export TERM="${TERM:-xterm}"
for test_file in "$ROOT"/server/tests/*.py; do
  printf '\n=== %s ===\n' "${test_file#$ROOT/}"
  python3 "$test_file"
done
