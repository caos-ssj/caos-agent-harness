#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

DEV=0
DESKTOP=0
SERVE=0
for arg in "$@"; do
  case "$arg" in
    --dev) DEV=1 ;;
    --desktop) DESKTOP=1 ;;
    --serve) SERVE=1 ;;
    *) echo "Uso: ./install.sh [--dev] [--desktop] [--serve]"; exit 1 ;;
  esac
done

PY=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PY="$cand"
      break
    fi
  fi
done
[ -n "$PY" ] || { echo "Se requiere Python 3.11+" >&2; exit 1; }

if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip --quiet
if [ "$DEV" -eq 1 ]; then
  .venv/bin/python -m pip install -e '.[dev]'
else
  .venv/bin/python -m pip install -e .
fi

if [ "$DESKTOP" -eq 1 ]; then
  for tool in node npm cargo rustc; do
    command -v "$tool" >/dev/null 2>&1 || { echo "Falta '$tool' para compilar CAOS Desktop" >&2; exit 1; }
  done
  TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"
  mkdir -p src-tauri/binaries
  .venv/bin/python -m pip install pyinstaller --quiet
  .venv/bin/python -m PyInstaller --noconfirm --clean --onefile \
    --name "caos-harness-sidecar-${TRIPLE}" \
    --distpath src-tauri/binaries \
    --collect-submodules caos_harness \
    --collect-data caos_harness \
    tools/sidecar_entry.py
  (cd web && npm ci && npm run build)
  ./web/node_modules/.bin/tauri build --config src-tauri/tauri.bundle.conf.json
fi

echo ""
echo "Listo. Comandos útiles:"
echo "  .venv/bin/caos-harness serve"
echo "  cd /ruta/a/tu/proyecto && $(pwd)/.venv/bin/caos-harness init --detect && $(pwd)/.venv/bin/caos-harness serve"

if [ "$SERVE" -eq 1 ]; then
  exec .venv/bin/caos-harness serve
fi
