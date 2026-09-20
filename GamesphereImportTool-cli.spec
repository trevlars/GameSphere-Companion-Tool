# PyInstaller spec — Linux CLI binary (gamesphere-import)
# Build: uv run build_cli.py

import os

block_cipher = None

hidden_imports = [
    "main",
    "gs_version",
    "gs_updater",
    "platform_paths",
    "store_scanners",
    "store_covers",
    "host_tuning",
    "host_tuning.config",
    "host_tuning.json_store",
    "host_tuning.service",
    "host_tuning.bridge",
    "host_tuning.link_speed",
    "host_tuning.session_telemetry",
    "host_tuning.app_stores",
    "host_tuning.tailscale",
    "host_tuning.host_assets",
    "host_tuning.managed_apps",
    "host_tuning.nvidia_sentinel",
    "host_tuning.display_audio",
    "host_tuning.launch_watcher",
    "host_tuning.lock_state",
    "host_tuning.stream_sockets",
    "host_tuning.couch_coop",
    "host_tuning.invite",
    "host_tuning.join_request",
    "host_tuning.voice_bridge",
    "host_tuning.wan_setup",
    "host_tuning.nat_map",
    "host_tuning.wanna_play",
    "host_tuning.coop_pause",
    "host_tuning.host_identity",
    "host_tuning.steam_playtime",
    "host_tuning.host_daemon",
    "mic_setup",
    "vban_feeder",
    "vdf",
    "PIL",
    "PIL.Image",
    "requests",
    "psutil",
    "dotenv",
    "glob2",
]

try:
    _spec_dir = os.path.dirname(os.path.abspath(SPEC))
except NameError:
    _spec_dir = os.getcwd()

_scripts = os.path.join(_spec_dir, "scripts")
datas_list = []
if os.path.isdir(_scripts):
    for name in (
        "gamesphere-steam-close.sh",
        "gamesphere-steam-close.py",
        "gamesphere-store-close.sh",
        "gamesphere-store-close.py",
        "gamesphere-host-prep.sh",
        "gamesphere-vban-setup.sh",
        "gamesphere-host-bridge.sh",
    ):
        p = os.path.join(_scripts, name)
        if os.path.isfile(p):
            datas_list.append((p, "scripts"))

a = Analysis(
    ["main.py"],
    pathex=[_spec_dir],
    binaries=[],
    datas=datas_list,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["customtkinter", "tkinter", "gui"],
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
    name="gamesphere-import",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
