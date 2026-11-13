#!/usr/bin/env bash
# Install CAOS Desktop launcher (.desktop + icon) into Linux applications menu and Desktop.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="${1:-$ROOT/src-tauri/target/release/caos-desktop}"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Escritorio")"

if [[ ! -x "$BIN" ]]; then
  echo "Binary not found at $BIN. Build it first with: make desktop-build" >&2
  exit 1
fi

mkdir -p "$APP_DIR" "$ICON_DIR"
cp "$ROOT/src-tauri/icons/128x128@2x.png" "$ICON_DIR/caos-desktop.png"
ICON_PATH="$ICON_DIR/caos-desktop.png"

write_entry() {
  local target="$1"
  cat > "$target" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=CAOS
GenericName=AI Agent Workstation
Comment=Local-first AI agent orchestrator, task board, and verification harness
Exec="$BIN"
TryExec=$BIN
Icon=$ICON_PATH
Terminal=false
Categories=Development;
StartupNotify=true
StartupWMClass=caos-desktop
EOF
  chmod +x "$target"
}

write_entry "$APP_DIR/caos-desktop.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" || true

if [[ -d "$DESKTOP_DIR" ]]; then
  write_entry "$DESKTOP_DIR/CAOS.desktop"
  command -v gio >/dev/null 2>&1 && gio set "$DESKTOP_DIR/CAOS.desktop" metadata::trusted true 2>/dev/null || true
  echo "Installed Desktop icon: $DESKTOP_DIR/CAOS.desktop"
fi

echo "Installed CAOS launcher: $APP_DIR/caos-desktop.desktop"
