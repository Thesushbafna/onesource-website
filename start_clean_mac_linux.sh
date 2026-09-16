#!/bin/sh
set -eu
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'Install Python 3.10 or newer, then run this script again.'
  exit 1
fi
printf '%s\n' 'Starting an empty PILOT workspace. Read README.md before entering actual records.'
exec python3 app.py --db data/onesource-pilot.sqlite3 --open
