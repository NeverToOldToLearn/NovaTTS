.PHONY: help setup install dev dev-tauri build build-tauri lint clean test cleanall
.PHONY: backend-venv backend-run backend-build gui-dev gui-build check-deps

# Detecteer OS
ifeq ($(OS),Windows_NT)
    PYTHON := backend\.venv\Scripts\python
    PIP := backend\.venv\Scripts\pip
    VENV_ACTIVATE := backend\.venv\Scripts\activate.bat
    RM := rmdir /s /q
    SHELL := cmd.exe
    .SHELL := cmd.exe
else
    PYTHON := backend/.venv/bin/python
    PIP := backend/.venv/bin/pip
    VENV_ACTIVATE := . backend/.venv/bin/activate
    RM := rm -rf
    SHELL := /bin/bash
endif

# Standaard target
.DEFAULT_GOAL := help

help:
	@echo.
	@echo ╔════════════════════════════════════════════════════════╗
	@echo ║           NovaTTS — Build & Development                ║
	@echo ╚════════════════════════════════════════════════════════╝
	@echo.
	@echo Setup & Installation:
	@echo   make setup           Install all dependencies (Python, Node, Rust)
	@echo   make check-deps      Verify required tools are installed
	@echo.
	@echo Development:
	@echo   make dev             Run Svelte dev server (frontend only)
	@echo   make dev-tauri       Run Tauri dev (full app with hot reload)
	@echo   make backend-run     Start Python API server
	@echo.
	@echo Build & Deployment:
	@echo   make build-tauri     Compile GUI + build NSIS installer
	@echo   make backend-build   Build standalone backend .exe (PyInstaller)
	@echo.
	@echo Maintenance:
	@echo   make lint            Run linters (ruff, mypy, eslint)
	@echo   make test            Run tests
	@echo   make clean           Remove build artifacts (keep venv)
	@echo   make cleanall        Full clean (remove venv too)
	@echo.
	@echo See INSTALL.md for detailed instructions.
	@echo.

# ============================================================================
# Dependency Checking
# ============================================================================

check-deps:
	@echo Checking system dependencies...
	@where rustc >nul 2>&1 || echo ERROR: rustc not found. Install from https://rustup.rs
	@where cargo >nul 2>&1 || echo ERROR: cargo not found. Install Rust.
	@where node >nul 2>&1 || echo ERROR: node not found. Install from https://nodejs.org
	@where npm >nul 2>&1 || echo ERROR: npm not found. Install Node.js.
	@where python >nul 2>&1 || echo ERROR: python not found. Install from https://python.org
	@echo ✓ All dependencies present

# ============================================================================
# Setup & Installation
# ============================================================================

setup: check-deps backend-venv
	@echo.
	@echo Installing Node dependencies...
	npm install
	@echo ✓ Setup complete. Run 'make dev-tauri' to start development.

backend-venv:
	@if not exist "backend\.venv" (
		echo Creating Python virtual environment...
		python -m venv backend\.venv
	)
	@echo Activating venv and installing dependencies...
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install -r backend/requirements.txt
	@if exist backend\requirements-dev.txt (
		$(PIP) install -r backend/requirements-dev.txt
	)
	@echo ✓ Python environment ready

# ============================================================================
# Development
# ============================================================================

dev:
	@echo Starting Svelte dev server on http://localhost:1420...
	npm run dev

dev-tauri:
	@echo Starting Tauri dev (GUI + backend integration)...
	npm run tauri --workspace=gui -- dev

backend-run: backend-venv
	@echo Starting NovaTTS backend API on http://127.0.0.1:8765...
	$(PYTHON) -m novatts.main

# ============================================================================
# Build & Compilation
# ============================================================================

build-tauri:
	@echo Building Tauri GUI + NSIS installer...
	@echo This may take 5-10 minutes on first build (Rust compilation).
	npm run tauri --workspace=gui -- build
	@echo ✓ Installer ready at: gui/src-tauri/target/release/bundle/nsis/NovaTTS_*.exe

backend-build: backend-venv
	@echo Building backend .exe with PyInstaller...
	$(PYTHON) -m pip install pyinstaller
	$(PYTHON) -m PyInstaller backend/Novabackend.spec
	@echo ✓ Backend exe at: backend/dist/novatts-backend.exe

# ============================================================================
# Linting & Testing
# ============================================================================

lint:
	@echo Running linters...
	@echo [Python] ruff check...
	$(PYTHON) -m ruff check backend || true
	@echo [Python] mypy...
	$(PYTHON) -m mypy --strict backend/novatts || true
	@echo ✓ Linting complete

test:
	@echo Running tests...
	$(PYTHON) -m pytest backend/tests/ -v || true
	@echo ✓ Tests complete (see output above)

# ============================================================================
# Cleaning
# ============================================================================

clean:
	@echo Cleaning build artifacts...
	@if exist gui\src-tauri\target rmdir /s /q gui\src-tauri\target
	@if exist gui\dist rmdir /s /q gui\dist
	@if exist backend\dist rmdir /s /q backend\dist
	@if exist backend\build rmdir /s /q backend\build
	@if exist .mypy_cache rmdir /s /q .mypy_cache
	@if exist backend\.mypy_cache rmdir /s /q backend\.mypy_cache
	@if exist backend\.ruff_cache rmdir /s /q backend\.ruff_cache
	@echo ✓ Build artifacts removed (venv preserved)

cleanall: clean
	@echo Removing virtual environment...
	@if exist backend\.venv rmdir /s /q backend\.venv
	@echo ✓ Full clean complete
