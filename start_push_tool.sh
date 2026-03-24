#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  # Prefer newer Python, but fall back to Python 3.9+ if that's all we have.
  for cand in python3.11 python3.10 python3.9 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      PYTHON_BIN="$cand"
      break
    fi
  done
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "Error: Python is required to run app.py." >&2
  exit 1
fi

# `app.py` contains annotations using PEP 604 (e.g. X | None).
# On Python < 3.10 those annotations may be evaluated at import time and crash.
if "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
  exec "$PYTHON_BIN" "$SCRIPT_DIR/app.py" --host "$HOST" --port "$PORT"
fi

# Python < 3.10: inject `from __future__ import annotations` at runtime
# so annotations are not evaluated immediately.
exec "$PYTHON_BIN" - "$SCRIPT_DIR/app.py" "$HOST" "$PORT" <<'PY'
import pathlib
import sys

script_path = pathlib.Path(sys.argv[1])
host = sys.argv[2]
port = sys.argv[3]

src = script_path.read_text(encoding="utf-8")
src = src.lstrip("\ufeff")  # Strip UTF-8 BOM if present
future = "from __future__ import annotations\n"
if not src.startswith(future):
    src = future + src

sys.argv = [str(script_path), "--host", host, "--port", port]
code = compile(src, str(script_path), "exec")
g = {"__file__": str(script_path), "__name__": "__main__"}
exec(code, g, g)
PY
