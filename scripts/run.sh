#!/bin/sh
# Run tg.py with the first working Python (python3, python, py).
# Probing with -c skips the Windows Store "python3" stub.
dir=$(dirname "$0")
for p in python3 python py; do
  if "$p" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >/dev/null 2>&1; then
    exec "$p" "$dir/tg.py" "$@"
  fi
done
echo "telegram-notify: Python 3.8+ not found" >&2
exit 0
