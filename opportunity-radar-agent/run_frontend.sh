#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [ -x .venv/bin/python ]; then
  PYTHON_BIN=.venv/bin/python
fi
exec "$PYTHON_BIN" -m streamlit run frontend/streamlit_app.py \
  --server.headless true \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  --browser.gatherUsageStats false
