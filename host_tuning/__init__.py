"""
Host-side streaming tuning for GameSphere Companion Tool.

Patterns adapted from StreamTweak (https://github.com/FoggyBytes/StreamTweak) — GPL-3.0.
"""

from host_tuning.config import HostTuningConfig, config_path, load_config, save_config
from host_tuning.service import apply_host_tuning, prep_start, prep_stop

__all__ = [
    "HostTuningConfig",
    "config_path",
    "load_config",
    "save_config",
    "apply_host_tuning",
    "prep_start",
    "prep_stop",
]
