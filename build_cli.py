#!/usr/bin/env python3
"""Build standalone Linux CLI binary (gamesphere-import) via PyInstaller."""

import sys


def main() -> None:
    if not sys.platform.startswith("linux"):
        print("Linux CLI binary builds on Linux only (GitHub Actions or a Linux VM).")
        sys.exit(1)
    try:
        import PyInstaller.__main__
    except ImportError:
        print("Install build deps: uv sync --extra build")
        sys.exit(1)
    PyInstaller.__main__.run(["GamesphereImportTool-cli.spec"])


if __name__ == "__main__":
    main()
