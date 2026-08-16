#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "Virtual environment not found."
  echo "Run ./setup.sh first."
  exit 1
fi
exec .venv/bin/python apex_oled_studio.py
