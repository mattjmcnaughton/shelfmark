#!/usr/bin/env bash
# Builds a self-contained Box release in the current checkout:
#   runtime/python  relocatable CPython (python-build-standalone) with dependencies
#   src/            application code, migrations, and the built frontend
# The Box runs `runtime/python/bin/python3 -m shelfmark`, so it needs no system Python.
set -euo pipefail

rm -rf runtime && mkdir -p runtime
UV_PYTHON_INSTALL_DIR="$PWD/runtime/.uv-python" uv python install 3.13 --no-bin >/dev/null
interpreter=$(realpath "$(UV_PYTHON_INSTALL_DIR="$PWD/runtime/.uv-python" uv python find 3.13 --managed-python)")
home=$(dirname "$(dirname "$interpreter")")
mv "$home" runtime/python
rm -rf runtime/.uv-python
python=runtime/python/bin/python3

uv export --frozen --no-dev --no-emit-project --no-hashes -o runtime/requirements.txt >/dev/null
uv pip install --python "$python" --break-system-packages --no-cache -r runtime/requirements.txt

(cd src/shelfmark/web/frontend && pnpm install --frozen-lockfile && pnpm build && rm -rf node_modules)
find src -name __pycache__ -prune -exec rm -rf {} +
