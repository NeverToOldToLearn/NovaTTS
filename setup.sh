#!/bin/bash
# NovaTTS — Setup script voor macOS / Linux
# Usage: bash setup.sh [--help] [--python-only] [--skip-python]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Kleuren
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    cat <<EOF
Usage: bash setup.sh [OPTIONS]

Options:
  --help              Toon deze help
  --python-only       Stel alleen Python env in (skip Node/Rust)
  --skip-python       Skip Python setup (alleen Node/Rust)

Voorbeeld:
  bash setup.sh                 # Volledige setup
  bash setup.sh --python-only   # Alleen Python venv
EOF
    exit 0
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        echo -e "${RED}✗ $1 niet gevonden${NC}"
        return 1
    fi
    echo -e "${GREEN}✓ $1$(command -v "$1" | xargs echo " —")${NC}"
    return 0
}

info() {
    echo -e "${YELLOW}→${NC} $1"
}

success() {
    echo -e "${GREEN}✓${NC} $1"
}

error() {
    echo -e "${RED}✗${NC} $1"
    exit 1
}

# Parse arguments
PYTHON_ONLY=0
SKIP_PYTHON=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help) usage ;;
        --python-only) PYTHON_ONLY=1; shift ;;
        --skip-python) SKIP_PYTHON=1; shift ;;
        *) error "Unknown option: $1" ;;
    esac
done

# ============================================================================
# 1. Check system dependencies
# ============================================================================

if [ $PYTHON_ONLY -eq 0 ]; then
    info "Checking system requirements..."
    
    check_command git || error "Git is required. Install from https://git-scm.com"
    check_command rustc || error "Rust is required. Install from https://rustup.rs"
    check_command cargo || error "Cargo is required (comes with Rust)"
    check_command node || error "Node.js is required. Install from https://nodejs.org"
    check_command npm || error "npm is required (comes with Node.js)"
    
    success "All system dependencies found"
fi

# ============================================================================
# 2. Python setup
# ============================================================================

if [ $SKIP_PYTHON -eq 0 ]; then
    info "Setting up Python virtual environment..."
    
    check_command python3 || error "Python 3 is required"
    
    if [ ! -d "backend/.venv" ]; then
        python3 -m venv backend/.venv
        success "Created virtual environment"
    else
        info "Virtual environment already exists"
    fi
    
    # Activate venv
    source backend/.venv/bin/activate
    
    info "Installing Python dependencies..."
    pip install --upgrade pip setuptools wheel
    
    if [ -f "backend/requirements.txt" ]; then
        pip install -r backend/requirements.txt
        success "Installed backend dependencies"
    else
        error "backend/requirements.txt not found"
    fi
    
    # Optional: dev dependencies
    if [ -f "backend/requirements-dev.txt" ]; then
        pip install -r backend/requirements-dev.txt
        success "Installed dev dependencies"
    fi
    
    deactivate
fi

# ============================================================================
# 3. Node.js / npm setup
# ============================================================================

if [ $PYTHON_ONLY -eq 0 ]; then
    info "Installing Node.js dependencies..."
    
    if [ ! -d "node_modules" ] || [ ! -d "gui/node_modules" ]; then
        npm install
        success "Installed npm dependencies"
    else
        info "Node dependencies already installed"
    fi
    
    # Verify tauri CLI
    if npm list @tauri-apps/cli &> /dev/null; then
        success "Tauri CLI is available"
    else
        error "Tauri CLI not found — npm install may have failed"
    fi
fi

# ============================================================================
# 4. Summary
# ============================================================================

echo
echo "═══════════════════════════════════════════════════════════════"
success "NovaTTS setup complete!"
echo "═══════════════════════════════════════════════════════════════"
echo
echo "Next steps:"
echo
if [ $SKIP_PYTHON -eq 0 ]; then
    echo "1. Activate Python venv:"
    echo "   source backend/.venv/bin/activate"
    echo
fi
if [ $PYTHON_ONLY -eq 0 ]; then
    echo "2. Start development:"
    echo "   npm run dev              # Svelte dev server"
    echo "   npm run dev-tauri        # Tauri dev (GUI + backend)"
    echo "   make dev-tauri           # or use Makefile"
    echo
    echo "3. Build installer:"
    echo "   npm run build-tauri      # or: make build-tauri"
    echo
fi
echo "See INSTALL.md for detailed instructions."
echo
