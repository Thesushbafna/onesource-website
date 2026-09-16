#!/bin/sh
set -eu
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'Install Python 3.10 or newer, then run this script again.'
  exit 1
fi
exec python3 app.py --demo --db data/onesource-demo.sqlite3 --open
