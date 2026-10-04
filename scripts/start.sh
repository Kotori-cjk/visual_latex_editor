#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python -m visual_latex_editor --open "$@"
fi
exec python3 -m visual_latex_editor --open "$@"
