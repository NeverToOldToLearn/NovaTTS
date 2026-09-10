.PHONY: setup install dev dev-tauri build build-tauri lint clean installer installer-zip installer-exe

setup:
	powershell -NoProfile -ExecutionPolicy Bypass -File ./setup.ps1

install: setup

installer:
	powershell -NoProfile -ExecutionPolicy Bypass -File ./installer/Build-Installer.ps1

installer-zip:
	powershell -NoProfile -ExecutionPolicy Bypass -File ./installer/Build-Installer.ps1 -ZipOnly

installer-exe:
	powershell -NoProfile -ExecutionPolicy Bypass -File ./installer/Build-Installer.ps1 -NoZip

dev:
	npm run dev --workspace=gui

dev-tauri:
	npm run tauri --workspace=gui -- dev

build:
	npm run build --workspace=gui

build-tauri:
	npm run tauri --workspace=gui -- build

lint:
	npm run build --workspace=gui
	backend/.venv/Scripts/python -m ruff check backend 2>nul || ruff check backend
	backend/.venv/Scripts/python -m mypy --strict backend/novatts 2>nul || mypy --strict backend/novatts

clean:
	powershell -NoProfile -Command "Remove-Item -Recurse -Force gui/dist,gui/node_modules,backend/.venv,backend/.ruff_cache,backend/.mypy_cache -ErrorAction SilentlyContinue; Write-Host 'clean done'"
