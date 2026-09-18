#!/usr/bin/env python3
"""
Build a standalone Windows .exe for GameSphere Companion Tool.
Run on Windows: uv run build_exe.py   or   python build_exe.py
Requires: uv sync --extra build   or   pip install pyinstaller
"""
import subprocess
import sys

def main():
    if sys.platform != "win32":
        print("Building the .exe is supported on Windows only.")
        print("Run this script on a Windows machine (or in a Windows CI/VM).")
        sys.exit(1)
    try:
        import PyInstaller.__main__
    except ImportError:
        print("PyInstaller not found. Install with:")
        print("  uv sync --extra build")
        print("  or: pip install pyinstaller")
        sys.exit(1)
    PyInstaller.__main__.run([
        "GamesphereImportTool.spec",
    ])

if __name__ == "__main__":
    main()
