#!/bin/sh
# Run pytest from venv if available, otherwise fall back to system python3
if [ -f ".venv/bin/python" ]; then
    .venv/bin/python -m pytest tests/ -q
else
    python3 -m pytest tests/ -q
fi
