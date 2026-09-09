# PyInstaller spec for Gamesphere Import Tool (Windows .exe)
# Build on Windows: pyinstaller GamesphereImportTool.spec
# Or: uv run pyinstaller GamesphereImportTool.spec

import sys

block_cipher = None

# When frozen, the GUI runs the importer in-process and needs the main module.
# Dynamic import in a thread is not traced, so include main explicitly.
hidden_imports = [
    'main',
    'gs_version',
    'gs_updater',
    'vdf',
    'PIL',
    'PIL.Image',
    'requests',
    'psutil',
    'dotenv',
    'glob2',
]

# Bundle GameSphere theme and logo (used by GUI)
# In .spec files __file__ is not set. PyInstaller injects SPEC (path to this .spec file).
import os
try:
    _spec_dir = os.path.dirname(os.path.abspath(SPEC))
except NameError:
    _spec_dir = os.getcwd()
_assets = os.path.join(_spec_dir, "assets")
datas_list = []
if os.path.isdir(_assets):
    for name in ("gamesphere_theme.json", "gamesphere_logo.png"):
        p = os.path.join(_assets, name)
        if os.path.isfile(p):
            datas_list.append((p, "assets"))
_scripts = os.path.join(_spec_dir, "scripts")
if os.path.isdir(_scripts):
    for name in (
        "gamesphere-steam-close.ps1",
        "gamesphere-steam-close.py",
        "gamesphere-steam-close.sh",
    ):
        p = os.path.join(_scripts, name)
        if os.path.isfile(p):
            datas_list.append((p, "scripts"))

# Optional: onefile=False produces a folder with .exe + dependencies (faster startup, easier antivirus)
# onefile=True produces a single .exe (simpler to distribute)
a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
    datas=datas_list,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GamesphereImportTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window for GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,  # Request admin so we can write to Program Files (Sunshine/Apollo config)
)
