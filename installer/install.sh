#!/usr/bin/env bash
# Linux build & install script for NovaTTS
# Usage: ./installer/install.sh [--no-backend] [--no-frontend]

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Resolve the repo root from the script location, so it works from any CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

VENV="$PROJECT_ROOT/venv"

# With `set -e` a failure can look like a silent exit. Make the cause explicit.
trap 'status=$?; echo -e "${RED}Error: \"$BASH_COMMAND\" failed (exit $status) at ${BASH_SOURCE[0]}:${LINENO}${NC}" >&2' ERR

echo -e "${GREEN}NovaTTS Linux Installer${NC}"
echo "Project root: $PROJECT_ROOT"

# Parse arguments
NO_BACKEND=false
NO_FRONTEND=false
for arg in "$@"; do
  case $arg in
    --no-backend) NO_BACKEND=true ;;
    --no-frontend) NO_FRONTEND=true ;;
  esac
done

# Function to check command existence
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

# Install system dependencies (Ubuntu/Debian)
install_system_deps() {
  echo -e "${YELLOW}Installing system dependencies...${NC}"
  # Update package lists
  sudo apt-get update -qq
  # Python, Node.js, and Rust toolchains
  sudo apt-get install -y -qq python3 python3-pip python3-venv nodejs npm cargo rustc build-essential
  # Runtime libraries: PortAudio for sounddevice, ffmpeg for audio conversion,
  # clipboard tools for pyperclip (X11 and Wayland)
  sudo apt-get install -y -qq libportaudio2 ffmpeg xclip wl-clipboard
  # Tauri (WebKitGTK) build dependencies for the Linux GUI
  sudo apt-get install -y -qq libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libayatana-appindicator3-dev patchelf
  echo -e "${GREEN}System dependencies installed.${NC}"
}

# Install Python dependencies
install_python_deps() {
  echo -e "${YELLOW}Installing Python dependencies...${NC}"
  if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
  fi
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
  echo -e "${GREEN}Python dependencies installed.${NC}"
}

# Install Node.js dependencies
install_node_deps() {
  echo -e "${YELLOW}Installing Node.js dependencies...${NC}"
  if ! command_exists npm; then
    # Install Node.js via nvm or n (if available)
    if command_exists n; then
      n install -g node
    else
      # Fallback: use NodeSource repository
      curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
      sudo apt-get install -y nodejs
    fi
  fi
  # Root package.json defines the "gui" workspace, so install from here.
  npm install
  # On a drive shared with Windows, node_modules may hold Windows .bin shims
  # that call node.exe. `npm rebuild` relinks them for Linux.
  if [ -f node_modules/.bin/vite ] && [ ! -L node_modules/.bin/vite ] \
     && grep -q "node.exe" node_modules/.bin/vite 2>/dev/null; then
    echo -e "${YELLOW}Found Windows npm shims; relinking for Linux...${NC}"
    npm rebuild
  fi
  echo -e "${GREEN}Node.js dependencies installed.${NC}"
}

# Build the application
build_app() {
  echo -e "${YELLOW}Building application...${NC}"
  # Build frontend (Svelte)
  npm run build
  # Build Python backend with PyInstaller (output: backend/dist/)
  if [ "$NO_BACKEND" = false ]; then
    (
      cd backend
      "$VENV/bin/pyinstaller" --noconfirm Novabackend.spec
    )
    # Verify the binary exists (PyInstaller produces it without extension on Linux).
    if [ ! -f backend/dist/novatts-backend ]; then
      echo -e "${RED}PyInstaller build did not produce backend/dist/novatts-backend${NC}" >&2
    fi
  fi
  # Build Tauri app (Linux binary). tauri.linux.conf.json overrides the
  # bundle targets to AppImage + deb automatically on Linux.
  if [ "$NO_FRONTEND" = false ]; then
    npm run tauri --workspace=gui -- build
  fi
  echo -e "${GREEN}Build complete.${NC}"
}

# Main flow
install_system_deps
if [ "$NO_BACKEND" = false ]; then
  install_python_deps
fi
# `npm run build` always runs, so Node deps are always needed.
install_node_deps
build_app

echo -e "${GREEN}NovaTTS is ready to run!${NC}"
if [ -x "$VENV/bin/python" ]; then
  echo "Run '$VENV/bin/python backend/run.py' to start the server."
else
  echo "Run 'python backend/run.py' to start the server."
fi
