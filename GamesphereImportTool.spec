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
    'platform_paths',
    'store_scanners',
    'store_covers',
    'host_tuning',
    'host_tuning.config',
    'host_tuning.service',
    'host_tuning.bridge',
    'host_tuning.link_speed',
    'host_tuning.session_telemetry',
    'host_tuning.app_stores',
    'host_tuning.tailscale',
    'host_tuning.host_assets',
    'host_tuning.managed_apps',
    'host_tuning.nvidia_sentinel',
    'host_tuning.display_audio',
    'host_tuning.launch_watcher',
    'host_tuning.lock_state',
    'host_tuning.stream_sockets',
    'host_tuning.couch_coop',
    'host_tuning.invite',
    'host_tuning.join_request',
    'host_tuning.voice_bridge',
    'host_tuning.wan_setup',
    'host_tuning.nat_map',
    'host_tuning.wanna_play',
    'host_tuning.coop_pause',
    'host_tuning.host_identity',
    'host_tuning.steam_playtime',
    'host_tuning.host_daemon',
    'mic_setup',
    'vban_feeder',
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
        "gamesphere-host-prep.ps1",
        "gamesphere-host-prep.sh",
        "gamesphere-vban-setup.ps1",
        "gamesphere-vban-setup.sh",
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
    console=False,  # No console window for GUI; --host-daemon stays hidden
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,  # Autostart must not UAC every logon; import can still be Run as administrator
)
