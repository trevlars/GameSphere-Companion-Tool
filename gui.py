"""
Gamesphere Import Tool — Windows GUI.
Configure paths, API key, and run the importer for Sunshine or Apollo.
"""

import os
import subprocess
import sys
import threading
import queue

from gs_updater import apply_update, check_for_update, format_notice
from gs_version import __version__ as APP_VERSION
from mic_setup import platform_label, setup_mic

# Optional: request admin on Windows so we can write to Program Files (Sunshine/Apollo config).
# Disabled at startup so the GUI always opens; user can right-click exe -> Run as administrator if needed.
def _request_admin_and_rerun():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        if ctypes.windll.shell32.IsUserAnAdmin():
            return  # Already admin
        # Re-launch with "runas" would exit this process and open GUI in elevated one,
        # which often leaves user with no visible window (UAC cancel or different session).
        # So we no longer do that here; GUI opens in current process.
    except Exception:
        pass

# Try CustomTkinter for modern look; fall back to tkinter
import tkinter as tk
from tkinter import messagebox, scrolledtext, filedialog
try:
    import customtkinter as ctk
    HAS_CTK = True
except ImportError:
    ctk = tk  # use standard tk
    HAS_CTK = False

# Env var names as used by main.py (load_dotenv + getenv)
ENV_KEYS = {
    "steam_library_vdf_path": "Steam library VDF path",
    "sunshine_apps_json_path": "Apps.json path",
    "sunshine_grids_folder": "Thumbnails folder",
    "steamgriddb_api_key": "SteamGridDB API key (optional; uses Steam CDN if empty)",
    "STEAM_EXE_PATH": "Steam executable (optional)",
    "SUNSHINE_EXE_PATH": "Host executable (optional)",
    "EPIC_MANIFESTS_PATH": "Epic Games manifests folder (optional)",
    "CUSTOM_GAMES_JSON_PATH": "Custom games JSON path (optional)",
    "XBOX_GAMES_FOLDERS": "Xbox/Windows games folder(s) (optional)",
    "SUNSHINE_SHORTCUTS_FOLDER": "Shortcuts folder (optional)",
}

# Default Windows paths per streaming host (main.py uses same env var names for both)
HOST_DEFAULTS = {
    "sunshine": {
        "steam_library_vdf_path": "C:/Program Files (x86)/Steam/steamapps/libraryfolders.vdf",
        "sunshine_apps_json_path": "C:/Program Files/Sunshine/config/apps.json",
        "sunshine_grids_folder": "C:/Sunshine_Thumbnails",
        "steamgriddb_api_key": "",
        "STEAM_EXE_PATH": "C:/Program Files (x86)/Steam/steam.exe",
        "SUNSHINE_EXE_PATH": "C:/Program Files/Sunshine/sunshine.exe",
        "EPIC_MANIFESTS_PATH": "C:/ProgramData/Epic/EpicGamesLauncher/Data/Manifests",
        "CUSTOM_GAMES_JSON_PATH": "",
        "XBOX_GAMES_FOLDERS": "C:/XboxGames",
        "SUNSHINE_SHORTCUTS_FOLDER": "",
    },
    "apollo": {
        "steam_library_vdf_path": "C:/Program Files (x86)/Steam/steamapps/libraryfolders.vdf",
        "sunshine_apps_json_path": "C:/Program Files/Apollo/config/apps.json",
        "sunshine_grids_folder": "C:/Apollo_Thumbnails",
        "steamgriddb_api_key": "",
        "STEAM_EXE_PATH": "C:/Program Files (x86)/Steam/steam.exe",
        "SUNSHINE_EXE_PATH": "C:/Program Files/Apollo/sunshine.exe",
        "EPIC_MANIFESTS_PATH": "C:/ProgramData/Epic/EpicGamesLauncher/Data/Manifests",
        "CUSTOM_GAMES_JSON_PATH": "",
        "XBOX_GAMES_FOLDERS": "C:/XboxGames",
        "SUNSHINE_SHORTCUTS_FOLDER": "",
    },
}

# For backwards compatibility (default host)
DEFAULTS = HOST_DEFAULTS["sunshine"]


def _base_dir():
    """Base directory for .env and main.py (script dir, or exe dir when frozen)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_dotenv_path():
    """Path to .env in the same directory as this script (or the .exe when frozen)."""
    return os.path.join(_base_dir(), ".env")


def load_env_from_file():
    """Load key=value pairs from .env into a dict. Returns (values_dict, host)."""
    path = get_dotenv_path()
    out = dict(DEFAULTS)
    host = "sunshine"
    if not os.path.exists(path):
        return out, host
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if key == "HOST":
                    host = value.lower() if value.lower() in ("sunshine", "apollo") else "sunshine"
                    continue
                if key in ENV_KEYS:
                    # Remove surrounding quotes if present
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    if value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    out[key] = value
    return out, host


def save_env_to_file(values, host="sunshine"):
    """Write config dict to .env."""
    path = get_dotenv_path()
    lines = [
        "# Gamesphere Import Tool configuration",
        "# Edit here or use the GUI. HOST = sunshine | apollo",
        "",
        f"HOST={host}",
        "",
    ]
    for key in ENV_KEYS:
        val = values.get(key, "")
        if " " in val or "#" in val:
            val = f'"{val}"'
        lines.append(f"{key}={val}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _run_importer_in_process(env_vars, dry_run, verbose, no_restart, log_queue, remove_games=False):
    """Run the importer in-process (used when frozen as .exe). Captures stdout to log_queue."""
    class QueueWriter:
        def __init__(self, q):
            self._q = q
        def write(self, s):
            if s:
                self._q.put(("out", s))
        def flush(self):
            pass

    base_dir = _base_dir()
    old_cwd = os.getcwd()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    out = QueueWriter(log_queue)
    sys.stdout, sys.stderr = out, out
    try:
        os.chdir(base_dir)
        for k, v in env_vars.items():
            if v:
                os.environ[k] = str(v)
        sys.argv = ["main.py"]
        if remove_games:
            sys.argv.append("--remove-games")
        if dry_run:
            sys.argv.append("--dry-run")
        if verbose:
            sys.argv.append("--verbose")
        if no_restart:
            sys.argv.append("--no-restart")
        import main as main_mod
        main_mod.main()
    except SystemExit as e:
        if e.code and e.code != 0:
            log_queue.put(("err", f"\nExited with code {e.code}\n"))
    except Exception as e:
        log_queue.put(("err", str(e) + "\n"))
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
        os.chdir(old_cwd)
    log_queue.put(("done",))


def run_automation(env_vars, dry_run, verbose, no_restart, log_queue, remove_games=False):
    """Run main.py in a subprocess (or in-process when frozen) and push lines to log_queue. Puts ("done",) when finished."""
    base_dir = _base_dir()
    is_frozen = getattr(sys, "frozen", False)

    if is_frozen:
        _run_importer_in_process(env_vars, dry_run, verbose, no_restart, log_queue, remove_games)
        return

    main_py = os.path.join(base_dir, "main.py")
    if not os.path.exists(main_py):
        log_queue.put(("err", "main.py not found.\n"))
        log_queue.put(("done",))
        return
    env = os.environ.copy()
    for k, v in env_vars.items():
        if v:
            env[k] = v
    cmd = [sys.executable, main_py]
    if remove_games:
        cmd.append("--remove-games")
    if dry_run:
        cmd.append("--dry-run")
    if verbose:
        cmd.append("--verbose")
    if no_restart:
        cmd.append("--no-restart")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=base_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in proc.stdout:
            log_queue.put(("out", line))
        proc.wait()
        if proc.returncode != 0:
            log_queue.put(("err", f"\nProcess exited with code {proc.returncode}\n"))
    except Exception as e:
        log_queue.put(("err", str(e) + "\n"))
    log_queue.put(("done",))


# GameSphere UI font (same family as tvOS app body/text, not the big title font)
if sys.platform == "darwin":
    _GS_FONT_FAMILY = "SF Pro Text"    # UI/body font in Apple apps (not SF Pro Display)
elif sys.platform == "win32":
    _GS_FONT_FAMILY = "Segoe UI"       # Windows UI font
else:
    _GS_FONT_FAMILY = "Sans"


def _gs_font(size=13, weight="normal"):
    """Font in GameSphere style (SF Pro–like per platform). Returns CTkFont or (family, size, weight) for tk."""
    if HAS_CTK:
        return ctk.CTkFont(family=_GS_FONT_FAMILY, size=size, weight=weight)
    return (_GS_FONT_FAMILY, size, weight)


# GameSphere accent (red from app icon) — buttons, cells, entries
if HAS_CTK:
    _GS_COLOR = ("#C42E1A", "#8B1A10")   # standard/darker red (cells, entries, unselected host btn)
    _GS_HOVER = ("#A32615", "#6D150C")   # hover
    _GS_LIGHT = ("#C42E1A", "#C42E1A")   # lighter red (all buttons default, selected host btn)

def _cell_red_kw():
    """Kwargs for frames that should use the same red as buttons (SettingsViewController style)."""
    if HAS_CTK:
        return {"fg_color": _GS_COLOR}
    return {"bg": "#8B1A10"}



def _icon_path():
    """Path to GameSphere logo for window icon (script dir or PyInstaller bundle)."""
    root = getattr(sys, "_MEIPASS", _base_dir())
    return os.path.join(root, "assets", "gamesphere_logo.png")


# GameSphere gradient (lighter top -> darker bottom, from app icon)
_GS_GRADIENT_TOP = "#C42E1A"
_GS_GRADIENT_BOTTOM = "#8B1A10"


def _hex_to_rgb(hex_str):
    h = hex_str.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(r, g, b):
    return "#{:02x}{:02x}{:02x}".format(int(r), int(g), int(b))


class SunshineGUI:
    def __init__(self):
        if HAS_CTK:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
        self.root = ctk.CTk() if HAS_CTK else tk.Tk()
        self.root.title(f"GameSphere Import Tool  v{APP_VERSION}")
        self.root.minsize(640, 620)
        self.root.geometry("760x820")
        self._set_app_icon()

        self.entries = {}
        self.host_var = None
        self.dry_run_var = None
        self.verbose_var = None
        self.no_restart_var = None
        self.run_btn = None
        self.remove_games_btn = None
        self.log_text = None
        self.log_queue = queue.Queue()
        self.running = False

        self._build_ui()
        self._load_config()
        self._poll_log()
        if os.environ.get("GAMESPHERE_SKIP_UPDATE_CHECK") != "1":
            self.root.after(1500, self._start_silent_update_check)

    def _set_app_icon(self):
        path = _icon_path()
        if not os.path.exists(path):
            return
        try:
            from tkinter import PhotoImage
            self._icon_img = PhotoImage(file=path)
            self.root.iconphoto(True, self._icon_img)
            # Windows taskbar/alt-tab use .ico; create from PNG if we have PIL
            if sys.platform == "win32":
                try:
                    import tempfile
                    from PIL import Image
                    img = Image.open(path).convert("RGBA")
                    ico_path = os.path.join(os.path.dirname(path), "gamesphere_logo.ico")
                    if not os.path.exists(ico_path):
                        try:
                            img.save(ico_path, format="ICO", sizes=[(32, 32), (16, 16)])
                        except OSError:
                            fd, ico_path = tempfile.mkstemp(suffix=".ico")
                            os.close(fd)
                            img.save(ico_path, format="ICO", sizes=[(32, 32), (16, 16)])
                    if os.path.exists(ico_path):
                        self.root.iconbitmap(ico_path)
                except Exception:
                    pass
        except Exception:
            pass

    def _frame(self, parent, **kwargs):
        if HAS_CTK:
            return ctk.CTkFrame(parent, **kwargs)
        return tk.Frame(parent, **kwargs)

    def _gradient_frame(self, parent):
        """Plain tk Frame with valid bg (empty string is invalid color on Windows)."""
        return tk.Frame(parent, bg=_GS_GRADIENT_BOTTOM)

    def _label(self, parent, text, **kwargs):
        kwargs.setdefault("font", _gs_font())
        if HAS_CTK:
            return ctk.CTkLabel(parent, text=text, **kwargs)
        return tk.Label(parent, text=text, **kwargs)

    def _entry(self, parent, **kwargs):
        kwargs.setdefault("font", _gs_font())
        if HAS_CTK:
            kwargs.setdefault("fg_color", _GS_COLOR)
            kwargs.setdefault("border_color", _GS_HOVER)
            return ctk.CTkEntry(parent, **kwargs)
        kwargs.setdefault("bg", "#8B1A10")
        kwargs.setdefault("fg", "white")
        return tk.Entry(parent, **kwargs)

    def _button(self, parent, text, command, **kwargs):
        kwargs.setdefault("font", _gs_font())
        if HAS_CTK:
            kwargs.setdefault("fg_color", _GS_LIGHT)
            kwargs.setdefault("hover_color", _GS_HOVER)
            return ctk.CTkButton(parent, text=text, command=command, **kwargs)
        return tk.Button(parent, text=text, command=command, **kwargs)

    def _checkbox(self, parent, text, variable, **kwargs):
        if HAS_CTK:
            kwargs.setdefault("fg_color", _GS_LIGHT)
            kwargs.setdefault("hover_color", _GS_HOVER)
            kwargs.setdefault("font", _gs_font())
            return ctk.CTkCheckBox(parent, text=text, variable=variable, **kwargs)
        kwargs.setdefault("font", _gs_font())
        return tk.Checkbutton(parent, text=text, variable=variable, **kwargs)

    def _on_host_change(self, choice):
        """Update path fields to defaults for the selected host."""
        host = choice.lower() if choice else "sunshine"
        if host not in HOST_DEFAULTS:
            host = "sunshine"
        self.host_var.set(host.capitalize())
        defaults = HOST_DEFAULTS[host]
        for key in ("sunshine_apps_json_path", "sunshine_grids_folder", "SUNSHINE_EXE_PATH"):
            self.entries[key].delete(0, "end")
            self.entries[key].insert(0, defaults.get(key, ""))
        self._update_host_buttons()

    def _update_host_buttons(self):
        """Selected host = lighter red; unselected = standard (darker) red."""
        if not HAS_CTK or not getattr(self, "_host_sunshine_btn", None):
            return
        current = (self.host_var.get() or "sunshine").lower()
        for name, btn in (("sunshine", self._host_sunshine_btn), ("apollo", self._host_apollo_btn)):
            selected = name == current
            btn.configure(
                fg_color=_GS_LIGHT if selected else _GS_COLOR,
                hover_color=_GS_HOVER,
            )

    def _on_canvas_configure(self, event):
        w, h = event.width, event.height
        pad = self._main_pad
        self._gradient_canvas.coords(self._main_win, pad, pad)
        self._gradient_canvas.itemconfig(self._main_win, width=max(0, w - 2 * pad), height=max(0, h - 2 * pad))
        self._draw_gradient(w, h)

    def _draw_gradient(self, w, h):
        if not getattr(self, "_gradient_canvas", None):
            return
        c = self._gradient_canvas
        c.delete("gradient")
        if w <= 0 or h <= 0:
            return
        # Dark at top, light at bottom
        r1, g1, b1 = _hex_to_rgb(_GS_GRADIENT_BOTTOM)
        r2, g2, b2 = _hex_to_rgb(_GS_GRADIENT_TOP)
        steps = max(2, min(80, h // 4))
        step = h / steps
        for i in range(steps):
            t = i / (steps - 1) if steps > 1 else 1
            r = r1 + (r2 - r1) * t
            g = g1 + (g2 - g1) * t
            b = b1 + (b2 - b1) * t
            color = _rgb_to_hex(r, g, b)
            y1, y2 = i * step, (i + 1) * step
            c.create_rectangle(0, y1, w, y2, fill=color, outline="", tags=("gradient",))

    def _build_ui(self):
        # Red gradient background (canvas behind content)
        self._gradient_canvas = tk.Canvas(
            self.root,
            highlightthickness=0,
            bg=_GS_GRADIENT_BOTTOM,
        )
        self._gradient_canvas.pack(fill="both", expand=True)
        main = self._gradient_frame(self._gradient_canvas)
        pad = 20
        self._main_win = self._gradient_canvas.create_window(pad, pad, window=main, anchor="nw")
        self._main_pad = pad
        main.update_idletasks()
        self._gradient_canvas.bind("<Configure>", self._on_canvas_configure)

        # Config section
        config_frame = self._gradient_frame(main)
        config_frame.pack(fill="x", pady=(0, 8))
        title_row = self._gradient_frame(config_frame)
        title_row.pack(fill="x")
        self._label(title_row, text="Configuration", font=_gs_font(14, "bold")).pack(side="left")
        self._version_label = self._label(title_row, text=f"v{APP_VERSION}", font=_gs_font(12))
        self._version_label.pack(side="right")

        # Streaming host: side-by-side buttons
        host_row = self._gradient_frame(config_frame)
        host_row.pack(fill="x", pady=(0, 6))
        self._label(host_row, text="Streaming host:", width=32, anchor="w").pack(side="left", padx=(0, 8))
        self.host_var = tk.StringVar(value="Sunshine")
        if HAS_CTK:
            btn_frame = self._gradient_frame(host_row)
            btn_frame.pack(side="left")
            self._host_sunshine_btn = ctk.CTkButton(
                btn_frame, text="Sunshine", width=120, font=_gs_font(),
                command=lambda: self._on_host_change("Sunshine"),
                fg_color=_GS_LIGHT, hover_color=_GS_HOVER,
            )
            self._host_sunshine_btn.pack(side="left", padx=(0, 6))
            self._host_apollo_btn = ctk.CTkButton(
                btn_frame, text="Apollo", width=120, font=_gs_font(),
                command=lambda: self._on_host_change("Apollo"),
                fg_color=_GS_COLOR, hover_color=_GS_HOVER,
            )
            self._host_apollo_btn.pack(side="left")
            self._update_host_buttons()
        else:
            self._host_sunshine_btn = tk.Button(host_row, text="Sunshine", width=12, command=lambda: self._on_host_change("Sunshine"))
            self._host_sunshine_btn.pack(side="left", padx=(0, 6))
            self._host_apollo_btn = tk.Button(host_row, text="Apollo", width=12, command=lambda: self._on_host_change("Apollo"))
            self._host_apollo_btn.pack(side="left")

        for key, label in ENV_KEYS.items():
            row = self._gradient_frame(config_frame)
            row.pack(fill="x", pady=2)
            self._label(row, text=label + ":", width=32, anchor="w").pack(side="left", padx=(0, 8))
            entry = self._entry(row)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
            self.entries[key] = entry
            if "optional" in label.lower():
                self._label(row, text="(optional)", font=_gs_font(9)).pack(side="left", padx=(8, 8))
            # Browse button for paths
            if "path" in key.lower() or "folder" in key.lower() or "json" in key.lower():
                def make_browse(e=entry, is_file=("json" in key or "vdf" in key)):
                    def browse():
                        if is_file:
                            path = filedialog.askopenfilename()
                        else:
                            path = filedialog.askdirectory()
                        if path:
                            e.delete(0, "end")
                            e.insert(0, path)
                    return browse
                btn = self._button(row, "Browse…", make_browse())
                btn.pack(side="right")

        # Options
        opt_frame = self._gradient_frame(main)
        opt_frame.pack(fill="x", pady=8)
        self._label(opt_frame, text="Options", font=_gs_font(14, "bold")).pack(anchor="w")
        self.dry_run_var = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=False)
        self.no_restart_var = tk.BooleanVar(value=False)
        self._checkbox(opt_frame, "Dry run (preview only)", self.dry_run_var).pack(anchor="w", pady=(0, 4))
        self._checkbox(opt_frame, "Verbose logging", self.verbose_var).pack(anchor="w", pady=(0, 4))
        self._checkbox(opt_frame, "Do not start Steam or restart host (Sunshine/Apollo)", self.no_restart_var).pack(anchor="w", pady=(0, 4))

        # Buttons
        btn_frame = self._gradient_frame(main)
        btn_frame.pack(fill="x", pady=8)
        self._button(btn_frame, "Save config", self._save_config).pack(side="left", padx=(0, 8))
        self.run_btn = self._button(btn_frame, "Run importer", self._on_run)
        self.run_btn.pack(side="left", padx=(0, 8))
        self.remove_games_btn = self._button(btn_frame, "Remove all games", self._on_remove_games)
        self.remove_games_btn.pack(side="left", padx=(0, 8))
        self.update_btn = self._button(btn_frame, "Check for updates", self._on_check_updates)
        self.update_btn.pack(side="left", padx=(0, 8))
        self.mic_btn = self._button(btn_frame, "Set up mic for GameSphere", self._on_setup_mic)
        self.mic_btn.pack(side="left")

        # Log (scrollable; gets most of the vertical space)
        self._label(main, text="Log", font=_gs_font(14, "bold")).pack(anchor="w")
        log_frame = self._gradient_frame(main)
        log_frame.pack(fill="both", expand=True, pady=4)
        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap="word", height=22, state="disabled",
            font=("Consolas", 14) if sys.platform == "win32" else ("Monaco", 14),
        )
        self.log_text.pack(fill="both", expand=True)

    def _load_config(self):
        values, host = load_env_from_file()
        for key, entry in self.entries.items():
            entry.delete(0, "end")
            entry.insert(0, values.get(key, ""))
        self.host_var.set(host.capitalize())
        self._update_host_buttons()

    def _get_values(self):
        return {key: entry.get().strip() for key, entry in self.entries.items()}

    def _get_host(self):
        raw = self.host_var.get().strip().lower()
        return raw if raw in ("sunshine", "apollo") else "sunshine"

    def _save_config(self):
        save_env_to_file(self._get_values(), self._get_host())
        messagebox.showinfo("Saved", "Configuration saved to .env")

    def _on_run(self):
        if self.running:
            return
        values = self._get_values()
        # SteamGridDB API key is optional; thumbnails use Steam CDN when not set
        required = [
            "steam_library_vdf_path",
            "sunshine_apps_json_path",
            "sunshine_grids_folder",
        ]
        missing = [k for k in required if not values.get(k)]
        if missing:
            messagebox.showerror(
                "Missing settings",
                "Please set: " + ", ".join(ENV_KEYS.get(k, k) for k in missing),
            )
            return
        # Save so CLI and subprocess see same config
        save_env_to_file(values, self._get_host())
        self.running = True
        self.run_btn.configure(state="disabled")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", "Running...\n\n")
        self.log_text.configure(state="disabled")
        self.log_queue = queue.Queue()
        thread = threading.Thread(
            target=run_automation,
            args=(
                values,
                self.dry_run_var.get(),
                self.verbose_var.get(),
                self.no_restart_var.get(),
                self.log_queue,
            ),
            daemon=True,
        )
        thread.start()

    def _on_remove_games(self):
        """Remove all games (Steam + manually added); keep only stock apps (Desktop, Steam, Virtual Display)."""
        if self.running:
            return
        values = self._get_values()
        apps_path = values.get("sunshine_apps_json_path", "").strip()
        if not apps_path:
            messagebox.showerror("Missing setting", "Please set the Apps.json path (Sunshine or Apollo config).")
            return
        if not messagebox.askyesno(
            "Remove all games",
            "Remove all games from the host (Steam games + manually added)? Only stock apps (Desktop, Steam, Virtual Display) will be kept, with their thumbnails. Game thumbnails in the grids folder will be removed.\n\nContinue?",
        ):
            return
        save_env_to_file(values, self._get_host())
        self.running = True
        self.run_btn.configure(state="disabled")
        self.remove_games_btn.configure(state="disabled")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", "Removing all games (keeping stock apps only)...\n\n")
        self.log_text.configure(state="disabled")
        self.log_queue = queue.Queue()
        thread = threading.Thread(
            target=run_automation,
            args=(
                values,
                False,
                self.verbose_var.get(),
                self.no_restart_var.get(),
                self.log_queue,
                True,  # remove_games
            ),
            daemon=True,
        )
        thread.start()

    def _start_silent_update_check(self):
        thread = threading.Thread(target=self._silent_update_worker, daemon=True)
        thread.start()

    def _silent_update_worker(self):
        try:
            info = check_for_update()
        except Exception:
            return
        if info.get("newer") and not info.get("error"):
            self.root.after(0, lambda: self._prompt_update(info, silent=True))

    def _on_setup_mic(self):
        """One-button Mic to PC: Windows VB-CABLE + feeder, Linux PipeWire — same UX."""
        if self.running:
            return
        plat = platform_label()
        if sys.platform == "win32":
            accept = messagebox.askyesno(
                "Set up mic for GameSphere",
                "GameSphere sends the phone mic to this PC over VBAN.\n\n"
                "On Windows we install VB-CABLE (VB-Audio donationware — "
                "not open source, not bundled) and start a small feeder "
                "that plays the phone into CABLE Input.\n\n"
                "• Stream name: GameSphere\n"
                "• UDP port: 6980\n"
                "• Discord microphone: CABLE Output\n"
                "• VoiceMeeter is not used\n\n"
                "Do you accept VB-Audio’s terms and continue?",
            )
            if not accept:
                return
        else:
            if not messagebox.askyesno(
                "Set up mic for GameSphere",
                f"Set up mic receive on {plat}?\n\n"
                "Linux uses PipeWire’s open-source VBAN module "
                "(stream GameSphere, UDP 6980).\n\n"
                "Continue?",
            ):
                return

        self.running = True
        try:
            self.mic_btn.configure(state="disabled")
            self.run_btn.configure(state="disabled")
        except Exception:
            pass
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"\n=== Set up mic for GameSphere ({plat}) ===\n")
        self.log_text.configure(state="disabled")
        self.log_queue = getattr(self, "log_queue", None) or queue.Queue()
        thread = threading.Thread(target=self._setup_mic_worker, daemon=True)
        thread.start()

    def _setup_mic_worker(self):
        def log_line(msg):
            self.log_queue.put(("log", msg + ("" if msg.endswith("\n") else "\n")))

        try:
            result = setup_mic(
                accept_third_party=(sys.platform == "win32"),
                info_only=False,
                log=log_line,
            )
            summary = result.summary()
            log_line(summary)
            self.root.after(0, lambda: self._finish_setup_mic(result))
        except Exception as exc:
            self.log_queue.put(("log", f"Mic setup failed: {exc}\n"))
            self.root.after(
                0,
                lambda: self._finish_setup_mic(
                    type("R", (), {"ok": False, "summary": lambda: str(exc), "lan_ips": [], "error": str(exc)})()
                ),
            )

    def _finish_setup_mic(self, result):
        self.running = False
        try:
            self.mic_btn.configure(state="normal")
            self.run_btn.configure(state="normal")
        except Exception:
            pass
        ips = getattr(result, "lan_ips", None) or []
        ip_line = ips[0] if ips else "(check log for LAN IP)"
        if getattr(result, "ok", False):
            reboot = getattr(result, "reboot_hint", False)
            extra = ""
            if reboot:
                extra = "\n\nReboot Windows once if CABLE Output is missing, then pick it in Discord."
            messagebox.showinfo(
                "Mic to PC",
                f"Mic receive is set up.\n\n"
                f"In GameSphere → Send mic to PC, enter:\n{ip_line}\n\n"
                f"Port 6980 · stream GameSphere\n\n"
                f"Discord microphone: CABLE Output\n\n"
                f"{getattr(result, 'recording_device_hint', '') or ''}".strip()
                + extra,
            )
        else:
            err = getattr(result, "error", None) or "See the log for details."
            messagebox.showwarning(
                "Mic to PC",
                f"Setup did not finish cleanly.\n\n{err}\n\n"
                "See docs/MIC-TO-PC.md or the log panel.",
            )

    def _on_check_updates(self):
        if self.running:
            return
        self.update_btn.configure(state="disabled")
        thread = threading.Thread(target=self._manual_update_worker, daemon=True)
        thread.start()

    def _manual_update_worker(self):
        try:
            info = check_for_update()
        except Exception as exc:
            info = {"error": str(exc), "newer": False, "current": APP_VERSION}
        self.root.after(0, lambda: self._finish_manual_update_check(info))

    def _finish_manual_update_check(self, info):
        try:
            self.update_btn.configure(state="normal")
        except Exception:
            pass
        if info.get("error"):
            messagebox.showwarning("Check for updates", format_notice(info))
            return
        if not info.get("newer"):
            messagebox.showinfo("Check for updates", format_notice(info))
            return
        self._prompt_update(info, silent=False)

    def _prompt_update(self, info, silent=False):
        latest = info.get("latest") or info.get("tag") or "a newer version"
        extra = ""
        if info.get("platform") == "win" and not info.get("asset"):
            extra = (
                "\n\nThe Windows installer is not attached to that release yet. "
                "Try again in a minute, or open the release page."
            )
        msg = (
            f"Version {latest} is available (you have {info.get('current')}).\n\n"
            "Download and install it now? The app will relaunch after the update."
            f"{extra}"
        )
        if not messagebox.askyesno("Update GameSphere Import Tool", msg):
            return
        self._apply_update_now(info)

    def _apply_update_now(self, info):
        self.running = True
        try:
            self.update_btn.configure(state="disabled")
            self.run_btn.configure(state="disabled")
        except Exception:
            pass
        thread = threading.Thread(target=self._apply_update_worker, args=(info,), daemon=True)
        thread.start()

    def _apply_update_worker(self, info):
        try:
            dest = apply_update(info)
            self.root.after(0, lambda: self._update_applied(dest, info))
        except Exception as exc:
            self.root.after(0, lambda: self._update_failed(exc, info))

    def _update_applied(self, dest, info):
        messagebox.showinfo(
            "Update installed",
            f"Updated to {info.get('latest')}.\n\n{dest}\n\nThe app will close so the new version can start.",
        )
        if sys.platform == "win32" and getattr(sys, "frozen", False):
            self.root.destroy()
            sys.exit(0)
        if sys.platform.startswith("linux"):
            wrapper = os.path.expanduser("~/.local/bin/gamesphere-import")
            if os.path.isfile(wrapper):
                try:
                    os.execv(wrapper, [wrapper])
                except OSError:
                    pass
        self.running = False
        try:
            self.update_btn.configure(state="normal")
            self.run_btn.configure(state="normal")
        except Exception:
            pass

    def _update_failed(self, exc, info):
        self.running = False
        try:
            self.update_btn.configure(state="normal")
            self.run_btn.configure(state="normal")
        except Exception:
            pass
        url = info.get("html_url") or ""
        messagebox.showerror(
            "Update failed",
            f"{exc}\n\nDownload manually:\n{url}",
        )

    def _poll_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg[0] == "done":
                    self.running = False
                    try:
                        self.run_btn.configure(state="normal")
                        self.remove_games_btn.configure(state="normal")
                    except Exception:
                        pass
                    continue
                kind, line = msg[0], msg[1]
                self.log_text.configure(state="normal")
                self.log_text.insert("end", line)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
                if line.startswith("BANNER:"):
                    banner_text = line[7:].strip()
                    if banner_text:
                        self.root.after(0, lambda t=banner_text: messagebox.showinfo("GameSphere Import Tool", t))
        except queue.Empty:
            pass
        self.root.after(200, self._poll_log)

    def run(self):
        self.root.mainloop()


def main():
    if "--vban-feeder-stop" in sys.argv:
        from vban_feeder import stop_feeder

        raise SystemExit(stop_feeder(print))
    if "--vban-feeder" in sys.argv:
        from vban_feeder import main as feeder_main

        argv = [a for a in sys.argv[1:] if a != "--vban-feeder"]
        raise SystemExit(feeder_main(argv))
    _request_admin_and_rerun()
    if sys.platform != "win32":
        print("This GUI is intended for Windows. On other platforms use: python main.py")
        # Still allow running for testing on Mac
    try:
        app = SunshineGUI()
        app.run()
    except Exception as e:
        messagebox.showerror("GameSphere Import Tool — Error", f"The application failed to start:\n\n{e}")
        raise


if __name__ == "__main__":
    main()
