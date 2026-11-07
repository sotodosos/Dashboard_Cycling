#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -x "$SCRIPT_DIR/venv/Scripts/python.exe" ]]; then
  PYTHON="$SCRIPT_DIR/venv/Scripts/python.exe"  # Git Bash en Windows
elif [[ -x "$SCRIPT_DIR/venv/bin/python" ]]; then
  PYTHON="$SCRIPT_DIR/venv/bin/python"          # Linux/macOS
else
  echo "No encuentro el intérprete del entorno virtual en venv/." >&2
  exit 1
fi

exec "$PYTHON" -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
