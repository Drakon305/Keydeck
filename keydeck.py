"""
KeyDeck - an on-screen button deck for Windows.
Click a button (or press its hotkey) and its saved text drops into whatever
text box you were typing in.

Python 3.9+
Install deps:   pip install keyboard pystray pillow pyperclip
Run:            pythonw keydeck.py
Build .exe:     pyinstaller --onefile --noconsole --name KeyDeck keydeck.py
"""

import ctypes
import faulthandler
import json
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import traceback

APP_NAME = "KeyDeck"
# Bump this for every release. GitHub builds and publishes a new KeyDeck.exe
# whenever this number changes, and running copies offer to update to it.
VERSION = "1.4.0"
GITHUB_REPO = "Drakon305/Keydeck"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_PATH = os.path.join(CONFIG_DIR, "startup.log")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# ---------------------------------------------------------------- logging ---
# Every run writes what it did to %APPDATA%\KeyDeck\startup.log

os.makedirs(CONFIG_DIR, exist_ok=True)
try:
    _log_file = open(LOG_PATH, "w", encoding="utf-8", buffering=1)
except Exception:
    _log_file = None


def log(msg):
    line = time.strftime("[%H:%M:%S] ") + str(msg)
    if _log_file:
        try:
            _log_file.write(line + "\n")
        except Exception:
            pass
    if sys.stdout:
        try:
            print(line)
        except Exception:
            pass


if _log_file:
    try:
        faulthandler.enable(_log_file)  # catches hard crashes too
    except Exception:
        pass


def fatal(title, msg):
    log(msg)
    try:
        ctypes.windll.user32.MessageBoxW(None, f"{title}\n\n{msg[-1500:]}\n\nLog: {LOG_PATH}", APP_NAME, 0x10)
    except Exception:
        pass


log(f"KeyDeck v{VERSION} starting. Python {sys.version.split()[0]}, frozen={getattr(sys, 'frozen', False)}, pid={os.getpid()}")

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog, filedialog
    import keyboard
    import pyperclip
    import pystray
    from PIL import Image, ImageDraw
except Exception:
    fatal("KeyDeck is missing a library it needs:", traceback.format_exc())
    sys.exit(1)

log("Libraries loaded")

MODIFIERS = ("ctrl", "alt", "shift", "left windows", "right windows")

# Colors
BG = "#1e1f24"
BAR_BG = "#2a2c33"
TABS_BG = "#16171b"
FG = "#e8e8ea"
DIM = "#8b8d96"
ACCENT = "#ffb347"
TILE = "#3a3d46"
SWATCHES = ["#3a3d46", "#c0392b", "#d35400", "#f39c12", "#27ae60",
            "#16a085", "#2980b9", "#8e44ad", "#e84393", "#7f8c8d"]

DEFAULT_BIND = {"label": "", "hotkey": "", "text": "", "mode": "paste",
                "enter": False, "enabled": True, "color": TILE,
                "action": "text",  # "text" = post text, "page" = jump to another page
                "goto": ""}        # id of the page to jump to (for action "page")
DEFAULT_CONFIG = {
    "pages": [
        {"name": "Main", "binds": [
            {**DEFAULT_BIND, "label": "Greeting", "hotkey": "ctrl+alt+1",
             "text": "Hey! Thanks for stopping by.", "color": "#2980b9"},
            {**DEFAULT_BIND, "label": "GG", "hotkey": "ctrl+alt+2",
             "text": "GG, well played!", "color": "#27ae60"},
        ]},
    ],
    "current_page": 0,
    "panel": {
        "x": None,
        "y": None,
        "w": None,
        "h": None,
        "opacity": 1.0,
        "columns": 4,
        "tile": 90,
        "font_size": 10,
        "show_hotkeys": True,
        "always_on_top": True,
        "toggle_hotkey": "ctrl+alt+p",
    },
}


# ----------------------------------------------------------------- config ---

def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data.get("pages"), list):
            pages = []
            for pg in data["pages"]:
                if not isinstance(pg, dict):
                    continue
                binds = pg.get("binds") if isinstance(pg.get("binds"), list) else []
                pages.append({"name": str(pg.get("name") or "Page"), "id": pg.get("id"),
                              "binds": [{**DEFAULT_BIND, **b} for b in binds if isinstance(b, dict)]})
            if pages:
                cfg["pages"] = pages
            cfg["current_page"] = data.get("current_page", 0)
        elif isinstance(data.get("binds"), list):  # older single-page setup
            cfg["pages"] = [{"name": "Main", "binds": [{**DEFAULT_BIND, **b}
                                                       for b in data["binds"] if isinstance(b, dict)]}]
        if isinstance(data.get("panel"), dict):
            for k in cfg["panel"]:
                if k in data["panel"]:
                    cfg["panel"][k] = data["panel"][k]
    except FileNotFoundError:
        pass
    except Exception:
        log("Config was unreadable, starting fresh:\n" + traceback.format_exc())
        try:
            os.replace(CONFIG_PATH, CONFIG_PATH + ".broken")
        except OSError:
            pass

    p = cfg["panel"]

    def num(key, lo, hi, cast=int):
        try:
            p[key] = max(lo, min(hi, cast(p[key])))
        except Exception:
            p[key] = DEFAULT_CONFIG["panel"][key]

    for key in ("x", "y", "w", "h"):
        try:
            p[key] = int(p[key]) if p[key] is not None else None
        except Exception:
            p[key] = None
    for key in ("w", "h"):
        if p[key] is not None and not (100 <= p[key] <= 10000):
            p[key] = None
    num("opacity", 0.3, 1.0, float)
    num("columns", 1, 12)
    num("tile", 50, 200)
    num("font_size", 7, 24)
    p["show_hotkeys"] = bool(p["show_hotkeys"])
    p["always_on_top"] = bool(p["always_on_top"])
    if not isinstance(p["toggle_hotkey"], str):
        p["toggle_hotkey"] = ""
    seen_ids = set()
    for pg in cfg["pages"]:
        pid = pg.get("id")
        if not isinstance(pid, str) or not pid or pid in seen_ids:
            pg["id"] = new_page_id()
        seen_ids.add(pg["id"])
        pg["binds"][:] = [clean_bind(b) for b in pg["binds"]]
    try:
        cur = int(cfg.get("current_page", 0))
    except Exception:
        cur = 0
    cfg["current_page"] = max(0, min(len(cfg["pages"]) - 1, cur))
    # cfg["binds"] always points at the list of buttons on the page you're looking at
    cfg["binds"] = cfg["pages"][cfg["current_page"]]["binds"]
    return cfg


EXPORT_FORMAT = 1


def new_page_id():
    import uuid
    return uuid.uuid4().hex[:10]


def clean_bind(b):
    """A safe, complete button from whatever a file contained."""
    b = {**DEFAULT_BIND, **{k: v for k, v in b.items() if k in DEFAULT_BIND}}
    if b.get("action") not in ("text", "page"):
        b["action"] = "text"
    for k in ("label", "hotkey", "text", "goto"):
        if not isinstance(b.get(k), str):
            b[k] = ""
    if b["mode"] not in ("paste", "type"):
        b["mode"] = "paste"
    b["enter"] = bool(b["enter"])
    b["enabled"] = bool(b["enabled"])
    if not isinstance(b.get("color"), str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", b["color"]):
        b["color"] = TILE
    return b


def save_export_file(path, pages):
    data = {"keydeck_export": EXPORT_FORMAT, "app_version": VERSION,
            "pages": [{"name": pg["name"], "id": pg.get("id"),
                       "binds": [dict(b) for b in pg["binds"]]} for pg in pages]}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def read_export_file(path):
    """Pages from a .keydeck export, a KeyDeck config.json, or an old single-page file."""
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    raw = None
    if isinstance(data, dict) and isinstance(data.get("pages"), list):
        raw = data["pages"]
    elif isinstance(data, dict) and isinstance(data.get("binds"), list):
        raw = [{"name": "Imported", "binds": data["binds"]}]
    if raw is None:
        raise ValueError("No KeyDeck pages found in this file.")
    pages = []
    for pg in raw:
        if not isinstance(pg, dict):
            continue
        binds = [clean_bind(b) for b in (pg.get("binds") or []) if isinstance(b, dict)]
        name = str(pg.get("name") or "Imported").strip()[:30] or "Imported"
        pid = pg.get("id") if isinstance(pg.get("id"), str) and pg.get("id") else new_page_id()
        pages.append({"name": name, "id": pid, "binds": binds})
    if not pages:
        raise ValueError("The file has no pages in it.")
    return pages


def remap_page_ids(new_pages, taken_ids):
    """Give imported pages fresh ids if they clash with ones you already have,
    and point their "go to page" buttons at the new ids."""
    mapping = {}
    for pg in new_pages:
        if pg["id"] in taken_ids or pg["id"] in mapping.values():
            nid = new_page_id()
            mapping[pg["id"]] = nid
            pg["id"] = nid
        taken_ids = set(taken_ids) | {pg["id"]}
    for pg in new_pages:
        for b in pg["binds"]:
            if b.get("action") == "page" and b.get("goto") in mapping:
                b["goto"] = mapping[b["goto"]]


def unique_name(name, existing):
    if name not in existing:
        return name
    n = 2
    while f"{name} ({n})" in existing:
        n += 1
    return f"{name} ({n})"


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        data = {k: v for k, v in cfg.items() if k != "binds"}  # binds live inside pages
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        log("Couldn't save config:\n" + traceback.format_exc())


# ---------------------------------------------------------------- hotkeys ---

def norm_hotkey(hk):
    return "+".join(p.strip().lower() for p in (hk or "").split("+") if p.strip())


def pretty_hotkey(hk):
    if not hk:
        return ""
    names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "windows": "Win",
             "left windows": "Win", "right windows": "Win"}
    parts = norm_hotkey(hk).split("+")
    return "+".join(names.get(p, p.upper() if len(p) == 1 else p.title()) for p in parts)


_RANDOM_RE = re.compile(r"\{([^{}]*\|[^{}]*)\}")


_CLIP_RE = re.compile(r"\{\s*(clipboard|clip|copied)\s*\}", re.IGNORECASE)


def read_clipboard():
    try:
        return (pyperclip.paste() or "").strip()
    except Exception:
        return ""


def expand_text(text, clip=None):
    """{a|b|c}      -> one option picked at random (nesting works: {hi|{hey|yo}})
    {clipboard}  -> whatever you last copied (also {clip} or {copied})
    Braces without a | in them are otherwise left alone."""
    for _ in range(20):  # inner groups first, so nesting works
        new = _RANDOM_RE.sub(lambda m: random.choice(m.group(1).split("|")), text)
        if new == text:
            break
        text = new
    # done last, so copied text is never treated as a random list
    if _CLIP_RE.search(text):
        if clip is None:
            clip = read_clipboard()
        text = _CLIP_RE.sub(lambda m: clip, text)
    return text


_STEP_RE = re.compile(r"\{\s*(enter|wait\s*:?\s*(\d+(?:\.\d+)?))\s*\}", re.IGNORECASE)


def plan_text(text, clip=None):
    """Turn a button's text into steps to perform, in order:
        ("text", "...")   paste/type this
        ("enter",)        press Enter          <- {enter}
        ("wait", 1.5)     pause this many sec  <- {wait 1.5}
    Random picks are resolved first; {clipboard} is filled in last, so copied
    text is never treated as a command."""
    for _ in range(20):
        new = _RANDOM_RE.sub(lambda m: random.choice(m.group(1).split("|")), text)
        if new == text:
            break
        text = new
    if clip is None and _CLIP_RE.search(text):
        clip = read_clipboard()
    steps, pos = [], 0
    for m in _STEP_RE.finditer(text):
        chunk = text[pos:m.start()]
        if chunk:
            steps.append(("text", _CLIP_RE.sub(lambda _: clip or "", chunk)))
        if m.group(1).lower().startswith("enter"):
            steps.append(("enter",))
        else:
            steps.append(("wait", min(30.0, float(m.group(2)))))
        pos = m.end()
    chunk = text[pos:]
    if chunk:
        steps.append(("text", _CLIP_RE.sub(lambda _: clip or "", chunk)))
    return steps


def describe_plan(steps):
    """Readable preview of what a button will do."""
    out = []
    for st in steps:
        if st[0] == "text":
            out.append(st[1])
        elif st[0] == "enter":
            out.append(" [Enter]\n")
        else:
            out.append(f"[wait {st[1]:g}s]")
    return "".join(out)


def valid_hotkey(hk):
    try:
        keyboard.parse_hotkey(hk)
        return True
    except Exception:
        return False


# ------------------------------------------------------------ windows glue ---

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetAncestor.restype = ctypes.c_void_p
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
user32.IsWindow.argtypes = [ctypes.c_void_p]
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int]


def startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    return f'"{exe}" "{os.path.abspath(__file__)}"'


def get_startup():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_startup(on):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass


# ---- single instance ---------------------------------------------------------

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = ctypes.c_void_p
_k32.CreateEventW.restype = ctypes.c_void_p
_k32.CloseHandle.argtypes = [ctypes.c_void_p]
_k32.SetEvent.argtypes = [ctypes.c_void_p]
_k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_mutex = None
_show_event = None
MUTEX_NAME = "Local\\KeyDeck_v4_single_instance"
EVENT_NAME = "Local\\KeyDeck_v4_show_panel"


def already_running():
    global _mutex, _show_event
    if _mutex:
        _k32.CloseHandle(_mutex)
    _mutex = _k32.CreateMutexW(None, False, MUTEX_NAME)
    running = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    if not _show_event:
        _show_event = _k32.CreateEventW(None, False, False, EVENT_NAME)
    return running


def signal_show():
    if _show_event:
        _k32.SetEvent(_show_event)


def show_requested():
    return bool(_show_event) and _k32.WaitForSingleObject(_show_event, 0) == 0


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
                ("th32ProcessID", ctypes.c_ulong), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
                ("th32ParentProcessID", ctypes.c_ulong), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_ulong), ("szExeFile", ctypes.c_wchar * 260)]


def list_processes():
    """[(pid, parent_pid, exe_name_lower), ...] for every running process."""
    out = []
    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W)]
    k.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    snap = k.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:
        return out
    try:
        e = _PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.append((e.th32ProcessID, e.th32ParentProcessID, e.szExeFile.lower()))
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return out


def kill_other_copies(names=("keydeck.exe", "keydrop.exe")):
    """End any other KeyDeck (or old KeyDrop) running in the background.
    Never touches this process or its own launcher process."""
    try:
        procs = list_processes()
        me = os.getpid()
        my_parent = next((pp for p, pp, n in procs if p == me), None)
        keep = {me, my_parent}
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        k.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        killed = 0
        for pid, ppid, name in procs:
            if name in names and pid not in keep and ppid != me:
                h = k.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
                if h:
                    if k.TerminateProcess(h, 0):
                        killed += 1
                    k.CloseHandle(h)
        log(f"Closed {killed} other copies")
        return True
    except Exception:
        log("kill_other_copies failed:\n" + traceback.format_exc())
        return False


# ---- self-install (so a single KeyDeck.exe can be shared) ----------------------

INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", APP_NAME)
INSTALLED_EXE = os.path.join(INSTALL_DIR, "KeyDeck.exe")


def version_tuple(s):
    return tuple(int(n) for n in re.findall(r"\d+", s or "")[:3]) or (0,)


def _http_get(url, timeout=15):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": f"KeyDeck/{VERSION}",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_latest_release():
    """(tag, exe_download_url, notes) for the newest published release."""
    with _http_get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest") as r:
        data = json.load(r)
    asset = next((a for a in data.get("assets", [])
                  if str(a.get("name", "")).lower() == "keydeck.exe"), None)
    return data.get("tag_name", ""), (asset or {}).get("browser_download_url"), data.get("body") or ""


def download_update(url):
    import tempfile
    folder = os.path.join(tempfile.gettempdir(), "KeyDeckUpdate")
    os.makedirs(folder, exist_ok=True)
    final = os.path.join(folder, "KeyDeck-update.exe")
    part = final + ".part"
    with _http_get(url, timeout=60) as r, open(part, "wb") as f:
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
    if os.path.getsize(part) < 1_000_000:  # a real build is several MB
        raise RuntimeError("The downloaded file looks incomplete.")
    if os.path.exists(final):
        os.remove(final)
    os.replace(part, final)
    return final


def make_shortcuts(target):
    ps = (
        "$s = New-Object -ComObject WScript.Shell; "
        "foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { "
        "  $l = $s.CreateShortcut((Join-Path $d 'KeyDeck.lnk')); "
        f"  $l.TargetPath = '{target}'; $l.WorkingDirectory = '{os.path.dirname(target)}'; "
        "  $l.Description = 'KeyDeck button deck'; $l.Save() }; "
        "foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { "
        "  Remove-Item -ErrorAction SilentlyContinue (Join-Path $d 'KeyDrop.lnk') }"
    )
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                   capture_output=True, creationflags=0x08000000)


def remove_old_keydrop():
    """Clean up the earlier KeyDrop version if it's on this PC."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, "KeyDrop")
    except OSError:
        pass
    old_cfg = os.path.join(os.environ.get("APPDATA", ""), "KeyDrop", "config.json")
    if os.path.exists(old_cfg) and not os.path.exists(CONFIG_PATH):
        try:
            import shutil
            shutil.copy2(old_cfg, CONFIG_PATH)  # keep your saved buttons
            log("Imported buttons from KeyDrop")
        except Exception:
            pass


def self_install_if_needed():
    """If this exe isn't running from the install folder, install it there,
    make shortcuts, start the installed copy, and return True."""
    if not getattr(sys, "frozen", False):
        return False
    here = os.path.normcase(os.path.abspath(sys.executable))
    if here == os.path.normcase(os.path.abspath(INSTALLED_EXE)):
        return False
    import shutil
    log(f"Installing from {sys.executable} to {INSTALLED_EXE}")
    try:
        was_installed = os.path.exists(INSTALLED_EXE)
        kill_other_copies()
        time.sleep(1.0)
        os.makedirs(INSTALL_DIR, exist_ok=True)
        for attempt in range(10):
            try:
                shutil.copy2(sys.executable, INSTALLED_EXE)
                break
            except PermissionError:
                time.sleep(0.5)
        else:
            raise RuntimeError("Couldn't replace the old KeyDeck.exe (it may still be running).")
        remove_old_keydrop()
        make_shortcuts(INSTALLED_EXE)
        subprocess.Popen([INSTALLED_EXE], cwd=INSTALL_DIR, close_fds=True,
                         creationflags=0x00000008 | 0x00000200)  # DETACHED | NEW_PROCESS_GROUP
        user32.MessageBoxW(
            None,
            ("KeyDeck has been updated." if was_installed else "KeyDeck is installed!") +
            "\n\nIt's opening now. Next time, open it from the KeyDeck shortcut on your "
            "Desktop or in the Start Menu.",
            APP_NAME, 0x40)
    except Exception:
        fatal("KeyDeck couldn't install:", traceback.format_exc())
    return True


# ---- window helpers ------------------------------------------------------------

def get_hwnd(win):
    return user32.GetAncestor(win.winfo_id(), 2)  # GA_ROOT


def is_own_window(hwnd):
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


def force_foreground(win):
    """Bring a window to the front with keyboard focus so you can type in it."""
    try:
        win.deiconify()
        win.update()
        win.lift()
        hwnd = get_hwnd(win)
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        me = kernel32.GetCurrentThreadId()
        attached = False
        if fg_tid and fg_tid != me:
            attached = bool(user32.AttachThreadInput(fg_tid, me, True))
        user32.ShowWindow(hwnd, 5)  # SW_SHOW
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if attached:
            user32.AttachThreadInput(fg_tid, me, False)
        win.focus_force()
    except Exception:
        log("force_foreground failed:\n" + traceback.format_exc())


def position_is_visible(x, y):
    gm = user32.GetSystemMetrics
    vx, vy, vw, vh = gm(76), gm(77), gm(78), gm(79)  # whole virtual screen
    if vw <= 0 or vh <= 0:
        return False
    return vx <= x <= vx + vw - 150 and vy <= y <= vy + vh - 100


def text_color_for(bg):
    try:
        c = bg.lstrip("#")
        r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
        return "#111111" if (0.299 * r + 0.587 * g + 0.114 * b) > 165 else "#ffffff"
    except Exception:
        return "#ffffff"


def make_icon_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((4, 4, 60, 60), fill=(42, 44, 51, 255), outline=(255, 179, 71, 255), width=4)
    for x, y in [(16, 16), (36, 16), (16, 36), (36, 36)]:
        d.rectangle((x, y, x + 12, y + 12), fill=(255, 179, 71, 255))
    return img


# ------------------------------------------------------------------ panel ---

class Panel:
    """The main KeyDeck window: a normal window with a title bar and taskbar button."""

    def __init__(self, app):
        self.app = app
        self.win = app.root
        self.edit_mode = False
        self._save_job = None
        p = app.cfg["panel"]

        w = self.win
        w.title("KeyDeck")
        w.configure(bg=BG)
        w.resizable(True, True)
        w.minsize(180, 110)
        w.protocol("WM_DELETE_WINDOW", app.quit)  # X = fully close KeyDeck
        try:
            from PIL import ImageTk
            self._icon = ImageTk.PhotoImage(make_icon_image())
            w.iconphoto(True, self._icon)
        except Exception:
            pass

        # toolbar
        bar = tk.Frame(w, bg=BAR_BG)
        bar.pack(fill="x")
        self.btn_edit = self._bar_btn(bar, "✎ Edit buttons", self.toggle_edit)
        self.btn_edit.pack(side="left")
        self._bar_btn(bar, "+ Add", lambda: app.edit_bind(None)).pack(side="left")
        self._bar_btn(bar, "⚙ Settings", app.open_settings).pack(side="right")

        # page tabs
        self.tabs = tk.Frame(w, bg=TABS_BG)
        self.tabs.pack(fill="x")

        self.hint = tk.Label(w, bg=BG, fg=ACCENT, font=("Segoe UI", 8),
                             text="Edit mode: click a button to change it. Click Done when finished.")
        self.grid_frame = tk.Frame(w, bg=BG, padx=6, pady=6)
        self.grid_frame.pack(fill="both", expand=True)

        self.rebuild()

        # position: last saved spot if it's on a screen, otherwise near the middle
        w.update_idletasks()
        x, y = p.get("x"), p.get("y")
        if x is None or y is None or not position_is_visible(x, y):
            x = max(0, (w.winfo_screenwidth() - w.winfo_reqwidth()) // 2)
            y = max(0, (w.winfo_screenheight() - w.winfo_reqheight()) // 3)
        ww, wh = p.get("w"), p.get("h")
        if ww and wh:  # restore the size you last dragged it to
            ww = min(ww, w.winfo_screenwidth())
            wh = min(wh, w.winfo_screenheight())
            w.geometry(f"{ww}x{wh}+{x}+{y}")
        else:
            w.geometry(f"+{x}+{y}")
        w.bind("<Configure>", self._on_move)

        w.deiconify()
        w.lift()
        w.update()
        force_foreground(w)
        log(f"Panel window: geometry={w.geometry()} state={w.state()} "
            f"visible={bool(user32.IsWindowVisible(get_hwnd(w)))}")

    def _bar_btn(self, parent, text, cmd):
        b = tk.Label(parent, text=text, bg=BAR_BG, fg=FG, padx=10, pady=5,
                     cursor="hand2", font=("Segoe UI", 9))
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.config(bg="#3a3d46"))
        b.bind("<Leave>", lambda e: b.config(bg=BAR_BG))
        return b

    def _on_move(self, e):
        if e.widget is not self.win:
            return
        if self._save_job:
            self.win.after_cancel(self._save_job)
        self._save_job = self.win.after(500, self._save_pos)

    def _save_pos(self):
        self._save_job = None
        if self.win.state() != "normal":
            return
        p = self.app.cfg["panel"]
        p["x"], p["y"] = self.win.winfo_x(), self.win.winfo_y()
        p["w"], p["h"] = self.win.winfo_width(), self.win.winfo_height()
        save_config(self.app.cfg)

    def reset_size(self):
        """Shrink/grow the window back to fit the buttons exactly."""
        p = self.app.cfg["panel"]
        p["w"] = p["h"] = None
        self.win.geometry("")
        save_config(self.app.cfg)

    # edit mode
    def toggle_edit(self):
        self.edit_mode = not self.edit_mode
        self.btn_edit.config(text="✓ Done editing" if self.edit_mode else "✎ Edit buttons",
                             fg=ACCENT if self.edit_mode else FG)
        if self.edit_mode:
            self.hint.pack(fill="x", before=self.grid_frame, pady=(4, 0))
        else:
            self.hint.pack_forget()
        self.rebuild()

    # page tabs
    def _build_tabs(self):
        for c in self.tabs.winfo_children():
            c.destroy()
        cfg = self.app.cfg
        cur = cfg["current_page"]
        for k, pg in enumerate(cfg["pages"]):
            on = k == cur
            t = tk.Label(self.tabs, text=pg["name"], padx=12, pady=4, cursor="hand2",
                         bg=BG if on else TABS_BG, fg=ACCENT if on else DIM,
                         font=("Segoe UI", 9, "bold" if on else "normal"))
            t.pack(side="left", padx=(0, 1))
            t.bind("<Button-1>", lambda e, k=k: self.app.switch_page(k))
            t.bind("<Double-Button-1>", lambda e, k=k: self.app.rename_page(k))
            t.bind("<Button-3>", lambda e, k=k: self._tab_menu(e, k))
            t.bind("<MouseWheel>", self._tab_wheel)
            if not on:
                t.bind("<Enter>", lambda e, t=t: t.config(fg=FG))
                t.bind("<Leave>", lambda e, t=t: t.config(fg=DIM))
        add = tk.Label(self.tabs, text="+ Page", padx=10, pady=4, cursor="hand2",
                       bg=TABS_BG, fg=DIM, font=("Segoe UI", 9))
        add.pack(side="left")
        add.bind("<Button-1>", lambda e: self.app.add_page())
        add.bind("<Enter>", lambda e: add.config(fg=ACCENT))
        add.bind("<Leave>", lambda e: add.config(fg=DIM))
        self.tabs.bind("<MouseWheel>", self._tab_wheel)

    def _tab_wheel(self, e):
        n = len(self.app.cfg["pages"])
        if n > 1:
            step = -1 if e.delta > 0 else 1
            self.app.switch_page((self.app.cfg["current_page"] + step) % n)

    def _tab_menu(self, e, k):
        n = len(self.app.cfg["pages"])
        m = tk.Menu(self.win, tearoff=0)
        m.add_command(label="Rename page", command=lambda: self.app.rename_page(k))
        m.add_command(label="Export this page…", command=lambda: self.app.export_pages([k]))
        m.add_command(label="Import buttons…", command=lambda: self.app.import_pages())
        m.add_command(label="Move left", command=lambda: self.app.move_page(k, -1),
                      state="normal" if k > 0 else "disabled")
        m.add_command(label="Move right", command=lambda: self.app.move_page(k, 1),
                      state="normal" if k < n - 1 else "disabled")
        m.add_separator()
        m.add_command(label="Delete page", command=lambda: self.app.delete_page(k),
                      state="normal" if n > 1 else "disabled")
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    # build the button grid
    def rebuild(self):
        self._build_tabs()
        p = self.app.cfg["panel"]
        self.win.attributes("-alpha", p["opacity"])
        self.win.attributes("-topmost", p["always_on_top"])
        for c in self.grid_frame.winfo_children():
            c.destroy()
        cols = p["columns"]
        binds = self.app.cfg["binds"]
        pos = 0
        for i, b in enumerate(binds):
            self._make_tile(i, b, pos // cols, pos % cols)
            pos += 1
        if self.edit_mode or not binds:
            self._make_add_tile(pos // cols, pos % cols)
            pos += 1

        # every row and column stretches equally, so the buttons fill the window
        rows = max(1, (pos + cols - 1) // cols)
        g = self.grid_frame
        used_cols = min(cols, max(pos, 1))
        for c in range(64):
            if c < used_cols:
                g.columnconfigure(c, weight=1, uniform="col")
            else:
                g.columnconfigure(c, weight=0, uniform="")
        for r in range(64):
            if r < rows:
                g.rowconfigure(r, weight=1, uniform="row")
            else:
                g.rowconfigure(r, weight=0, uniform="")

    def _tile_frame(self, row, col, color):
        size = self.app.cfg["panel"]["tile"]
        f = tk.Frame(self.grid_frame, bg=color, width=size, height=size,
                     highlightthickness=2, highlightbackground=BG, cursor="hand2")
        f.grid(row=row, column=col, padx=3, pady=3, sticky="nsew")
        f.pack_propagate(False)
        return f, size

    def _make_tile(self, i, b, row, col):
        p = self.app.cfg["panel"]
        fs = p["font_size"]
        on = b.get("enabled", True)
        color = b["color"] if on else "#2b2d33"
        fg = text_color_for(color) if on else "#6b6d75"
        f, size = self._tile_frame(row, col, color)
        if self.edit_mode:
            f.config(highlightbackground=ACCENT)

        is_link = b.get("action") == "page"
        target = self.app.page_by_id(b.get("goto")) if is_link else None
        if is_link:
            title = b["label"] or (target["name"] if target else "(missing page)")
        else:
            title = b["label"] or " ".join(b["text"].split())[:40] or "(empty)"
        name = tk.Label(f, text=title, bg=color, fg=fg, font=("Segoe UI", fs, "bold"),
                        wraplength=max(20, size - 12), justify="center", cursor="hand2")
        name.pack(expand=True, fill="both", padx=4, pady=(4, 0))
        # re-wrap the label text whenever the button gets wider or narrower
        name.bind("<Configure>", lambda e, n=name: n.config(wraplength=max(20, e.width - 8)), add="+")
        widgets = [f, name]
        sub = []
        if is_link:
            sub.append("→ " + (target["name"] if target else "missing page"))
        if p["show_hotkeys"] and b["hotkey"]:
            sub.append(pretty_hotkey(b["hotkey"]))
        if sub:
            hk = tk.Label(f, text="  ".join(sub), bg=color, fg=fg,
                          font=("Consolas", max(7, fs - 3)), cursor="hand2")
            hk.pack(side="bottom", pady=(0, 4))
            widgets.append(hk)

        def enter(e):
            f.config(highlightbackground=FG)

        def leave(e):
            f.config(highlightbackground=ACCENT if self.edit_mode else BG)

        for w in widgets:
            w.bind("<Button-1>", lambda e, i=i, ws=widgets, c=color: self._on_click(i, ws, c))
            w.bind("<Button-3>", lambda e, i=i: self.app.edit_bind(i))  # right-click = edit
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    def _make_add_tile(self, row, col):
        f, size = self._tile_frame(row, col, BG)
        f.config(highlightbackground=DIM)
        lbl = tk.Label(f, text="+", bg=BG, fg=DIM, font=("Segoe UI", 22), cursor="hand2")
        lbl.pack(expand=True, fill="both")
        for w in (f, lbl):
            w.bind("<Button-1>", lambda e: self.app.edit_bind(None))
            w.bind("<Enter>", lambda e: lbl.config(fg=ACCENT))
            w.bind("<Leave>", lambda e: lbl.config(fg=DIM))

    def _on_click(self, i, widgets, color):
        if self.edit_mode:
            self.app.edit_bind(i)
            return
        b = self.app.cfg["binds"][i]
        if not b.get("enabled", True):
            return
        if b.get("action") == "page":
            self.app.goto_page(b.get("goto"))
            return
        for w in widgets:  # quick flash so you know it fired
            w.config(bg=ACCENT)
        self.win.after(150, lambda: [w.config(bg=color) for w in widgets if w.winfo_exists()])
        self.app.post(b, from_click=True)

    # show / minimize
    def is_shown(self):
        return self.win.state() == "normal"

    def show(self):
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        if not self.app.cfg["panel"]["always_on_top"]:
            self.win.after(200, lambda: self.win.attributes("-topmost", False))

    def minimize(self):
        self.win.iconify()

    def toggle(self):
        self.minimize() if self.is_shown() else self.show()


# ----------------------------------------------------------- bind editor ---

class BindEditor:
    def __init__(self, app, index=None):
        self.app, self.index = app, index
        editing = index is not None
        b = {**DEFAULT_BIND, **(app.cfg["binds"][index] if editing else {})}

        d = self.win = tk.Toplevel(app.root)
        d.title("Edit button" if editing else "New button")
        d.geometry("560x580")
        d.minsize(480, 520)
        d.attributes("-topmost", True)
        d.protocol("WM_DELETE_WINDOW", self.close)

        f = ttk.Frame(d, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        f.rowconfigure(2, weight=1)

        ttk.Label(f, text="Button name").grid(row=0, column=0, sticky="w")
        self.label = tk.StringVar(value=b["label"])
        self.label_entry = ttk.Entry(f, textvariable=self.label)
        self.label_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=3)

        ttk.Label(f, text="Hotkey (optional)").grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.hotkey = tk.StringVar(value=b["hotkey"])
        ttk.Entry(f, textvariable=self.hotkey).grid(row=1, column=1, sticky="ew", pady=3)
        hkb = ttk.Frame(f)
        hkb.grid(row=1, column=2, padx=(6, 0))
        self.rec_btn = ttk.Button(hkb, text="Record", command=self.record)
        self.rec_btn.pack(side="left")
        ttk.Button(hkb, text="Clear", command=lambda: self.hotkey.set("")).pack(side="left", padx=(4, 0))

        ttk.Label(f, text="Text to post").grid(row=2, column=0, sticky="nw", pady=3)
        tf = ttk.Frame(f)
        tf.grid(row=2, column=1, columnspan=2, sticky="nsew", pady=3)
        self.text = tk.Text(tf, height=7, wrap="word", font=("Segoe UI", 10), undo=True)
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", b["text"])
        tip = ttk.Frame(tf)
        tip.pack(fill="x", pady=(3, 0))
        ttk.Label(tip, foreground="#666666", font=("Segoe UI", 8),
                  text="{a|b|c} random   {clipboard} last copied   {enter} press Enter   {wait 1} pause"
                  ).pack(side="left")
        ttk.Button(tip, text="Preview", command=self.preview).pack(side="right")

        ttk.Label(f, text="Color").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.color = b["color"] or TILE
        sw = tk.Frame(f)
        sw.grid(row=3, column=1, columnspan=2, sticky="w", pady=(6, 0))
        self.swatches = []
        for c in SWATCHES:
            s = tk.Label(sw, bg=c, width=3, height=1, cursor="hand2", bd=3, relief="flat")
            s.pack(side="left", padx=2)
            s.bind("<Button-1>", lambda e, c=c: self.pick_color(c))
            self.swatches.append((c, s))
        self.pick_color(self.color)

        ttk.Label(f, text="Shown on page").grid(row=4, column=0, sticky="w", pady=(6, 0))
        page_names = [f'{k + 1}. {pg["name"]}' for k, pg in enumerate(app.cfg["pages"])]
        self.page_box = ttk.Combobox(f, values=page_names, state="readonly", width=24)
        self.page_box.current(app.cfg["current_page"])
        self.page_box.grid(row=4, column=1, sticky="w", pady=(6, 0))

        opts = ttk.Frame(f)
        opts.grid(row=5, column=1, columnspan=2, sticky="w", pady=(8, 0))

        # what the button does: post its text, or jump to another page
        act = ttk.Frame(opts)
        act.pack(anchor="w", pady=(0, 6))
        self.action = tk.StringVar(value=b.get("action", "text"))
        ttk.Radiobutton(act, text="Post the text", variable=self.action, value="text",
                        command=self._action_changed).pack(side="left")
        ttk.Radiobutton(act, text="Go to page:", variable=self.action, value="page",
                        command=self._action_changed).pack(side="left", padx=(12, 4))
        self._page_ids = [pg["id"] for pg in app.cfg["pages"]]
        self.goto_box = ttk.Combobox(act, values=[pg["name"] for pg in app.cfg["pages"]],
                                     state="readonly", width=18)
        if b.get("goto") in self._page_ids:
            self.goto_box.current(self._page_ids.index(b["goto"]))
        self.goto_box.pack(side="left")
        self.goto_box.bind("<<ComboboxSelected>>", lambda e: self.action.set("page"))

        self.mode = tk.StringVar(value=b["mode"])
        ttk.Radiobutton(opts, text="Paste it (fast, works almost everywhere)",
                        variable=self.mode, value="paste").pack(anchor="w")
        ttk.Radiobutton(opts, text="Type it out (for apps that block pasting)",
                        variable=self.mode, value="type").pack(anchor="w")
        self.enter = tk.BooleanVar(value=b["enter"])
        ttk.Checkbutton(opts, text="Press Enter after (auto-send in chats)",
                        variable=self.enter).pack(anchor="w")
        self.enabled = tk.BooleanVar(value=b["enabled"])
        ttk.Checkbutton(opts, text="Enabled", variable=self.enabled).pack(anchor="w")

        bb = ttk.Frame(f)
        bb.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        if editing:
            ttk.Button(bb, text="Delete", command=self.delete).pack(side="left")
            ttk.Button(bb, text="◀ Move", command=lambda: self.move(-1)).pack(side="left", padx=(6, 0))
            ttk.Button(bb, text="Move ▶", command=lambda: self.move(1)).pack(side="left", padx=(4, 0))
        ttk.Button(bb, text="Cancel", command=self.close).pack(side="right")
        ttk.Button(bb, text="Save", command=self.save).pack(side="right", padx=(0, 6))

        force_foreground(d)
        d.after(80, lambda: force_foreground(d) if d.winfo_exists() else None)
        (self.text if editing else self.label_entry).focus_set()

    def _action_changed(self):
        if self.action.get() == "page" and self.goto_box.current() < 0:
            self.goto_box.focus_set()
            self.goto_box.event_generate("<Down>")  # open the list so you can pick

    def preview(self):
        raw = self.text.get("1.0", "end-1c")
        samples = "\n\n".join(f"{n}) {describe_plan(plan_text(raw))}" for n in range(1, 4))
        messagebox.showinfo(APP_NAME, f"Three sample results:\n\n{samples}", parent=self.win)

    def pick_color(self, c):
        self.color = c
        for col, s in self.swatches:
            s.config(relief="solid" if col == c else "flat")

    def record(self):
        self.rec_btn.config(text="Press combo…", state="disabled")

        def done(hk):
            if not self.win.winfo_exists():
                return
            self.rec_btn.config(text="Record", state="normal")
            if hk:
                self.hotkey.set(norm_hotkey(hk))

        self.app.record_hotkey(done)

    def save(self):
        hk = norm_hotkey(self.hotkey.get())
        text = self.text.get("1.0", "end-1c")
        err = None
        action = self.action.get()
        goto = ""
        if action == "page":
            k = self.goto_box.current()
            if k < 0:
                err = "Pick which page this button should go to."
            else:
                goto = self._page_ids[k]
        elif not text.strip():
            err = "Type the text this button should post."
        if not err and hk:
            if not valid_hotkey(hk):
                err = f'"{hk}" isn\'t a valid hotkey. Try Record, or leave it blank.'
            else:
                clash = self.app.find_conflict(hk, skip_index=self.index)
                if clash:
                    err = f"{pretty_hotkey(hk)} is already used by {clash}."
        if err:
            messagebox.showerror(APP_NAME, err, parent=self.win)
            return
        data = {"label": self.label.get().strip(), "hotkey": hk, "text": text,
                "mode": self.mode.get(), "enter": self.enter.get(),
                "enabled": self.enabled.get(), "color": self.color,
                "action": action, "goto": goto}
        cur = self.app.cfg["current_page"]
        target = self.page_box.current()
        if target < 0:
            target = cur
        if target == cur:
            if self.index is None:
                self.app.cfg["binds"].append(data)
            else:
                self.app.cfg["binds"][self.index] = data
        else:  # moved to another page
            if self.index is not None:
                del self.app.cfg["binds"][self.index]
            self.app.cfg["pages"][target]["binds"].append(data)
        self.app.apply()
        self.close()

    def delete(self):
        name = self.app.cfg["binds"][self.index].get("label") or "this button"
        if messagebox.askyesno(APP_NAME, f'Delete "{name}"?', parent=self.win):
            del self.app.cfg["binds"][self.index]
            self.app.apply()
            self.close()

    def move(self, step):
        binds = self.app.cfg["binds"]
        j = self.index + step
        if not (0 <= j < len(binds)):
            return
        binds[self.index], binds[j] = binds[j], binds[self.index]
        self.index = j
        self.app.apply()

    def close(self):
        if self.app.editor is self:
            self.app.editor = None
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# --------------------------------------------------------------- settings ---

class SettingsWindow:
    def __init__(self, app):
        self.app = app
        p = app.cfg["panel"]
        w = self.win = tk.Toplevel(app.root)
        w.title(f"{APP_NAME} Settings")
        w.geometry("480x520")
        w.attributes("-topmost", True)
        w.protocol("WM_DELETE_WINDOW", self.close)

        f = ttk.Frame(w, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(f, text="Buttons per row").grid(row=r, column=0, sticky="w")
        self.columns = tk.IntVar(value=p["columns"])
        ttk.Spinbox(f, from_=1, to=12, textvariable=self.columns, width=6).grid(row=r, column=1, sticky="w", pady=3)
        r += 1
        ttk.Label(f, text="Button size (px)").grid(row=r, column=0, sticky="w")
        self.tile = tk.IntVar(value=p["tile"])
        ttk.Spinbox(f, from_=50, to=200, increment=5, textvariable=self.tile, width=6).grid(row=r, column=1, sticky="w", pady=3)
        r += 1
        ttk.Label(f, text="Font size").grid(row=r, column=0, sticky="w")
        self.font_size = tk.IntVar(value=p["font_size"])
        ttk.Spinbox(f, from_=7, to=24, textvariable=self.font_size, width=6).grid(row=r, column=1, sticky="w", pady=3)
        r += 1
        ttk.Label(f, text="Opacity").grid(row=r, column=0, sticky="w")
        self.opacity = tk.DoubleVar(value=p["opacity"])
        ttk.Scale(f, from_=0.3, to=1.0, variable=self.opacity,
                  command=lambda v: app.root.attributes("-alpha", float(v))
                  ).grid(row=r, column=1, sticky="ew", pady=3)
        r += 1
        ttk.Label(f, text="Show/hide hotkey").grid(row=r, column=0, sticky="w", padx=(0, 8))
        hkrow = ttk.Frame(f)
        hkrow.grid(row=r, column=1, sticky="w", pady=3)
        self.toggle_hk = tk.StringVar(value=p["toggle_hotkey"])
        ttk.Entry(hkrow, textvariable=self.toggle_hk, width=18).pack(side="left")
        self.toggle_rec = ttk.Button(hkrow, text="Record", command=self.record_toggle)
        self.toggle_rec.pack(side="left", padx=(6, 0))
        r += 1
        self.on_top = tk.BooleanVar(value=p["always_on_top"])
        ttk.Checkbutton(f, text="Keep KeyDeck on top of other windows", variable=self.on_top
                        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
        r += 1
        self.show_hotkeys = tk.BooleanVar(value=p["show_hotkeys"])
        ttk.Checkbutton(f, text="Show hotkeys on buttons", variable=self.show_hotkeys
                        ).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        self.startup = tk.BooleanVar(value=get_startup())
        ttk.Checkbutton(f, text="Start KeyDeck with Windows", variable=self.startup,
                        command=self.toggle_startup).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        errs = app.hotkey_errors
        ttk.Label(f, foreground="#c0392b", wraplength=430, justify="left",
                  text=("Some hotkeys couldn't be registered:\n" + "\n".join(errs)) if errs else ""
                  ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))
        r += 1
        bb = ttk.Frame(f)
        bb.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(bb, text="Quit KeyDeck", command=app.quit).pack(side="left")
        ttk.Button(bb, text="Uninstall", command=self.uninstall).pack(side="left", padx=(6, 0))
        ttk.Button(f, text="Fit window to buttons", command=app.panel.reset_size
                   ).grid(row=r + 1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        upd = ttk.Frame(f)
        upd.grid(row=r + 2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(upd, text=f"Version {VERSION}").pack(side="left")
        ttk.Button(upd, text="Check for updates",
                   command=lambda: app.check_for_updates(manual=True)).pack(side="left", padx=(8, 0))
        bk = ttk.Frame(f)
        bk.grid(row=r + 3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(bk, text="Backup & share:").pack(side="left")
        ttk.Button(bk, text="Export buttons…", command=lambda: app.export_pages(parent=w)
                   ).pack(side="left", padx=(8, 0))
        ttk.Button(bk, text="Import buttons…", command=lambda: app.import_pages(parent=w)
                   ).pack(side="left", padx=(6, 0))
        self._orig_layout = (p["columns"], p["tile"])
        ttk.Button(bb, text="Close", command=self.close).pack(side="right")
        ttk.Button(bb, text="Save", command=self.save).pack(side="right", padx=(0, 6))

        force_foreground(w)
        w.after(80, lambda: force_foreground(w) if w.winfo_exists() else None)

    def record_toggle(self):
        self.toggle_rec.config(text="Press combo…", state="disabled")

        def done(hk):
            if not self.win.winfo_exists():
                return
            self.toggle_rec.config(text="Record", state="normal")
            if hk:
                self.toggle_hk.set(norm_hotkey(hk))

        self.app.record_hotkey(done)

    def uninstall(self):
        if not messagebox.askyesno(APP_NAME, "Uninstall KeyDeck from this PC?", parent=self.win):
            return
        keep = messagebox.askyesno(APP_NAME, "Keep your saved buttons in case you reinstall later?",
                                   parent=self.win)
        try:
            set_startup(False)
        except Exception:
            pass
        ps = ("foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) "
              "{ Remove-Item -ErrorAction SilentlyContinue (Join-Path $d 'KeyDeck.lnk') }")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, creationflags=0x08000000)
        # delete the program folder (and settings if asked) a moment after KeyDeck closes
        targets = [f'rmdir /s /q "{INSTALL_DIR}"']
        if not keep:
            targets.append(f'rmdir /s /q "{CONFIG_DIR}"')
        cmd = "timeout /t 3 /nobreak >nul & " + " & ".join(targets)
        subprocess.Popen(["cmd", "/c", cmd], creationflags=0x08000000 | 0x00000008)
        messagebox.showinfo(APP_NAME, "KeyDeck has been uninstalled.", parent=self.win)
        try:
            if _log_file:
                _log_file.close()
        except Exception:
            pass
        self.app.quit()

    def toggle_startup(self):
        try:
            set_startup(self.startup.get())
        except Exception as e:
            self.startup.set(get_startup())
            messagebox.showerror(APP_NAME, f"Couldn't change startup setting:\n{e}", parent=self.win)

    def save(self):
        hk = norm_hotkey(self.toggle_hk.get())
        if hk:
            if not valid_hotkey(hk):
                messagebox.showerror(APP_NAME, f'"{hk}" isn\'t a valid hotkey.', parent=self.win)
                return
            clash = self.app.find_conflict(hk, check_toggle=False)
            if clash:
                messagebox.showerror(APP_NAME, f"{pretty_hotkey(hk)} is already used by {clash}.",
                                     parent=self.win)
                return

        def num(var, lo, hi, default):
            try:
                return max(lo, min(hi, int(var.get())))
            except (tk.TclError, ValueError):
                return default

        self.app.cfg["panel"].update(
            columns=num(self.columns, 1, 12, 4),
            tile=num(self.tile, 50, 200, 90),
            font_size=num(self.font_size, 7, 24, 10),
            opacity=round(float(self.opacity.get()), 2),
            show_hotkeys=self.show_hotkeys.get(),
            always_on_top=self.on_top.get(),
            toggle_hotkey=hk,
        )
        p = self.app.cfg["panel"]
        layout_changed = (p["columns"], p["tile"]) != self._orig_layout
        self.app.apply()
        if layout_changed:  # new grid shape: refit the window to it
            self.app.panel.reset_size()
        self.close()

    def close(self):
        if self.app.settings is self:
            self.app.settings = None
        self.app.panel.rebuild()  # undo an unsaved opacity preview
        try:
            self.win.destroy()
        except tk.TclError:
            pass


# -------------------------------------------------------------------- app ---

def _index_of(items, obj):
    """Index of this exact object (not just an equal-looking one), or None."""
    return next((i for i, x in enumerate(items) if x is obj), None)


class App:
    def __init__(self):
        self.cfg = load_config()
        save_config(self.cfg)
        log("Config loaded")
        self.root = tk.Tk()
        self.root.report_callback_exception = self._report_error
        self.ui_queue = queue.Queue()
        self.post_queue = queue.Queue()
        self.hotkey_errors = []
        self._last_fire = {}
        self.settings = None
        self.editor = None
        self.last_target = None  # last outside window you were typing in
        self.tray = None

        self.panel = Panel(self)
        log("Panel created")
        threading.Thread(target=self._post_worker, daemon=True).start()
        self.register_hotkeys()
        log(f"Hotkeys registered ({len(self.hotkey_errors)} errors)")

        # Tray icon is an extra; if it fails, the window still works.
        try:
            self.tray = pystray.Icon(APP_NAME, make_icon_image(), APP_NAME, menu=pystray.Menu(
                pystray.MenuItem("Show / hide KeyDeck", lambda icon, item: self.ui(self.panel.toggle), default=True),
                pystray.MenuItem("Add a button", lambda icon, item: self.ui(self.edit_bind, None)),
                pystray.MenuItem("Settings", lambda icon, item: self.ui(self.open_settings)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", lambda icon, item: self.ui(self.quit)),
            ))
            self.tray.run_detached()
            log("Tray icon running")
        except Exception:
            self.tray = None
            log("Tray icon failed (window still works):\n" + traceback.format_exc())

        self.root.after(30, self._poll)
        self._updating = False
        self.root.after(4000, lambda: self.check_for_updates(manual=False))

    # ---- auto-update --------------------------------------------------------
    def check_for_updates(self, manual=False):
        """Look at the latest GitHub release in the background."""
        if self._updating:
            return

        def worker():
            try:
                tag, url, notes = fetch_latest_release()
                self.ui(self._offer_update, tag, url, notes, manual)
            except Exception as e:
                log(f"Update check failed: {e}")
                if manual:
                    self.ui(lambda: messagebox.showwarning(
                        APP_NAME, f"Couldn't check for updates right now.\n\n{e}", parent=self.root))

        threading.Thread(target=worker, daemon=True).start()

    def _offer_update(self, tag, url, notes, manual):
        if not tag or version_tuple(tag) <= version_tuple(VERSION):
            log(f"Up to date (v{VERSION}, latest {tag or 'none'})")
            if manual:
                messagebox.showinfo(APP_NAME, f"You're up to date (version {VERSION}).", parent=self.root)
            return
        new = tag.lstrip("vV")
        if not getattr(sys, "frozen", False) or not url:
            if manual:
                messagebox.showinfo(APP_NAME, f"Version {new} is available on GitHub:\n"
                                    f"https://github.com/{GITHUB_REPO}/releases/latest", parent=self.root)
            return
        notes = (notes or "").strip()
        if len(notes) > 600:
            notes = notes[:600] + "…"
        msg = f"KeyDeck {new} is available (you have {VERSION})."
        if notes:
            msg += f"\n\nWhat's new:\n{notes}"
        msg += "\n\nUpdate now? It takes a few seconds and keeps all your buttons."
        if messagebox.askyesno(APP_NAME, msg, parent=self.root):
            self._download_and_install(url, new)

    def _download_and_install(self, url, new):
        self._updating = True
        self.root.title(f"KeyDeck - downloading update {new}…")

        def worker():
            try:
                path = download_update(url)
                log(f"Update {new} downloaded to {path}; handing over")
                # The downloaded exe installs itself over this one (closing us first),
                # then opens the new version.
                subprocess.Popen([path], cwd=os.path.dirname(path), close_fds=True,
                                 creationflags=0x00000008 | 0x00000200)
                self.ui(self.quit)
            except Exception as e:
                log("Update download failed:\n" + traceback.format_exc())

                def fail():
                    self._updating = False
                    self.root.title("KeyDeck")
                    messagebox.showerror(APP_NAME, f"The update couldn't be downloaded.\n\n{e}",
                                         parent=self.root)
                self.ui(fail)

        threading.Thread(target=worker, daemon=True).start()

    def _report_error(self, exc, val, tb):
        msg = "".join(traceback.format_exception(exc, val, tb))
        log("Error:\n" + msg)
        try:
            messagebox.showerror(APP_NAME, f"Something went wrong:\n\n{val}\n\nLog: {LOG_PATH}")
        except Exception:
            pass

    # thread-safe UI calls
    def ui(self, fn, *args):
        self.ui_queue.put((fn, args))

    def _poll(self):
        try:
            while True:
                fn, args = self.ui_queue.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    self._report_error(*sys.exc_info())
        except queue.Empty:
            pass
        try:
            if show_requested():  # KeyDeck was opened again: bring the window back
                log("Show requested by a second launch")
                self.panel.show()
                force_foreground(self.root)
            fg = user32.GetForegroundWindow()
            if fg and not is_own_window(fg):
                self.last_target = fg
        except Exception:
            pass
        self.root.after(30, self._poll)

    # hotkeys
    def register_hotkeys(self):
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        self.hotkey_errors = []
        for _, _, b in self.all_binds():  # hotkeys work no matter which page is showing
            if not (b.get("enabled", True) and b.get("hotkey")):
                continue
            try:
                keyboard.add_hotkey(b["hotkey"], self._on_hotkey, args=(dict(b),),
                                    suppress=False, trigger_on_release=True)
            except Exception as e:
                self.hotkey_errors.append(f'{b.get("label") or b["hotkey"]}: {e}')
        thk = self.cfg["panel"].get("toggle_hotkey")
        if thk:
            try:
                keyboard.add_hotkey(thk, lambda: self.ui(self.panel.toggle),
                                    suppress=False, trigger_on_release=True)
            except Exception as e:
                self.hotkey_errors.append(f"Show/hide: {e}")
        for e in self.hotkey_errors:
            log("Hotkey error: " + e)

    def record_hotkey(self, on_done):
        try:
            keyboard.unhook_all_hotkeys()  # so existing binds don't fire while recording
        except Exception:
            pass

        def worker():
            try:
                hk = keyboard.read_hotkey(suppress=False)
            except Exception:
                hk = ""

            def finish():
                self.register_hotkeys()
                on_done(hk)

            self.ui(finish)

        threading.Thread(target=worker, daemon=True).start()

    def all_binds(self):
        for k, pg in enumerate(self.cfg["pages"]):
            for i, b in enumerate(pg["binds"]):
                yield k, i, b

    def find_conflict(self, hk, skip_index=None, check_toggle=True):
        n = norm_hotkey(hk)
        cur = self.cfg["current_page"]
        for k, i, b in self.all_binds():
            if (k, i) == (cur, skip_index):
                continue
            if b.get("hotkey") and norm_hotkey(b["hotkey"]) == n:
                where = "" if k == cur else f' on page "{self.cfg["pages"][k]["name"]}"'
                return f'"{b.get("label") or "another button"}"{where}'
        if check_toggle and norm_hotkey(self.cfg["panel"].get("toggle_hotkey")) == n:
            return "the show/hide hotkey"
        return None

    def _on_hotkey(self, b):
        now = time.time()
        if now - self._last_fire.get(b["hotkey"], 0) < 0.35:
            return
        self._last_fire[b["hotkey"]] = now
        if b.get("action") == "page":
            self.ui(self.goto_page, b.get("goto"), True)
            return
        self.post(b)

    def post(self, b, from_click=False):
        self.post_queue.put((dict(b), from_click))

    # posting text
    def _post_worker(self):
        while True:
            b, from_click = self.post_queue.get()
            try:
                if from_click and not self._restore_target():
                    log("No window to type into yet; click into a text box first.")
                    continue
                self._wait_for_modifiers()
                for step in plan_text(b["text"]):
                    if step[0] == "text":
                        if b.get("mode") == "type":
                            keyboard.write(step[1], delay=0.003)
                        else:
                            self._paste(step[1])
                    elif step[0] == "enter":
                        time.sleep(0.06)
                        keyboard.send("enter")
                        time.sleep(0.15)  # give chats a moment to send before the next part
                    else:
                        time.sleep(step[1])
                if b.get("enter"):
                    time.sleep(0.06)
                    keyboard.send("enter")
            except Exception:
                log("Post failed:\n" + traceback.format_exc())

    def _restore_target(self):
        """Clicking a KeyDeck button focuses KeyDeck, so hand focus back to
        the window you were typing in before pasting."""
        try:
            fg = user32.GetForegroundWindow()
            if fg and not is_own_window(fg):
                return True
            t = self.last_target
            if not (t and user32.IsWindow(t)):
                return False
            for _ in range(3):
                user32.SetForegroundWindow(t)
                time.sleep(0.06)
                if user32.GetForegroundWindow() == t:
                    break
            time.sleep(0.05)
            return True
        except Exception:
            return False

    @staticmethod
    def _pressed(key):
        try:
            return keyboard.is_pressed(key)
        except Exception:
            return False

    def _wait_for_modifiers(self, timeout=2.0):
        # Wait until you let go of Ctrl/Alt/Shift, otherwise Ctrl+V becomes Ctrl+Alt+V.
        end = time.time() + timeout
        while time.time() < end and any(self._pressed(m) for m in MODIFIERS):
            time.sleep(0.015)
        time.sleep(0.03)

    @staticmethod
    def _paste(text):
        try:
            prev = pyperclip.paste()
        except Exception:
            prev = None
        pyperclip.copy(text)
        time.sleep(0.04)
        keyboard.send("ctrl+v")
        time.sleep(0.3)
        if prev:  # put back whatever you had copied before
            try:
                pyperclip.copy(prev)
            except Exception:
                pass

    # windows
    def edit_bind(self, index=None):
        if self.editor:
            self.editor.close()
        if index is not None and not (0 <= index < len(self.cfg["binds"])):
            return
        self.panel.show()
        self.editor = BindEditor(self, index)

    # pages
    def page_by_id(self, pid):
        return next((pg for pg in self.cfg["pages"] if pg.get("id") == pid), None) if pid else None

    def goto_page(self, pid, from_hotkey=False):
        """What a "go to page" button does."""
        k = next((k for k, pg in enumerate(self.cfg["pages"]) if pg.get("id") == pid), None)
        if k is None:
            if not from_hotkey:
                messagebox.showinfo(APP_NAME, "The page this button goes to was deleted.\n"
                                    "Right-click the button to pick another page.", parent=self.root)
            return
        if from_hotkey:
            self.panel.show()
        self.switch_page(k)

    def _set_page(self, k):
        k = max(0, min(len(self.cfg["pages"]) - 1, k))
        self.cfg["current_page"] = k
        self.cfg["binds"] = self.cfg["pages"][k]["binds"]

    def switch_page(self, k):
        if k == self.cfg["current_page"]:
            return
        if self.editor:
            self.editor.close()
        self._set_page(k)
        self.apply()

    def _ask_name(self, title, initial=""):
        name = simpledialog.askstring(APP_NAME, title, initialvalue=initial, parent=self.root)
        return name.strip()[:30] if name and name.strip() else None

    def add_page(self):
        name = self._ask_name("Name for the new page:", f"Page {len(self.cfg['pages']) + 1}")
        if not name:
            return
        if self.editor:
            self.editor.close()
        self.cfg["pages"].append({"name": name, "id": new_page_id(), "binds": []})
        self._set_page(len(self.cfg["pages"]) - 1)
        self.apply()

    def rename_page(self, k):
        name = self._ask_name("Rename page:", self.cfg["pages"][k]["name"])
        if name:
            self.cfg["pages"][k]["name"] = name
            self.apply()

    def move_page(self, k, step):
        pages = self.cfg["pages"]
        j = k + step
        if not (0 <= j < len(pages)):
            return
        cur_page = pages[self.cfg["current_page"]]
        pages[k], pages[j] = pages[j], pages[k]
        self._set_page(_index_of(pages, cur_page))
        self.apply()

    def delete_page(self, k):
        pages = self.cfg["pages"]
        if len(pages) <= 1:
            return
        pg = pages[k]
        msg = f'Delete the page "{pg["name"]}"'
        msg += f' and its {len(pg["binds"])} button(s)?' if pg["binds"] else "?"
        if not messagebox.askyesno(APP_NAME, msg, parent=self.root):
            return
        if self.editor:
            self.editor.close()
        cur_page = pages[self.cfg["current_page"]]
        del pages[k]
        i = _index_of(pages, cur_page)
        self._set_page(i if i is not None else min(k, len(pages) - 1))
        self.apply()

    # ---- backup & share -----------------------------------------------------
    def export_pages(self, page_indexes=None, parent=None):
        """Save pages (all of them, or just some) to a .keydeck file."""
        parent = parent or self.root
        pages = self.cfg["pages"]
        chosen = [pages[k] for k in (page_indexes if page_indexes is not None else range(len(pages)))]
        default = (chosen[0]["name"] if len(chosen) == 1 else "My KeyDeck buttons")
        default = re.sub(r'[\\/:*?"<>|]+', "", default).strip() or "KeyDeck buttons"
        path = filedialog.asksaveasfilename(
            parent=parent, title="Save your KeyDeck buttons",
            initialdir=os.path.join(os.path.expanduser("~"), "Documents"),
            initialfile=f"{default}.keydeck", defaultextension=".keydeck",
            filetypes=[("KeyDeck buttons", "*.keydeck"), ("All files", "*.*")])
        if not path:
            return
        try:
            save_export_file(path, chosen)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Couldn't save the file.\n\n{e}", parent=parent)
            return
        n = sum(len(pg["binds"]) for pg in chosen)
        messagebox.showinfo(
            APP_NAME, f"Saved {n} button(s) on {len(chosen)} page(s) to:\n{path}\n\n"
            "Keep it as a backup, or send it to a friend - they can load it with "
            "Settings > Import buttons.", parent=parent)

    def import_pages(self, parent=None):
        """Load pages from a .keydeck file (or a KeyDeck config.json)."""
        parent = parent or self.root
        path = filedialog.askopenfilename(
            parent=parent, title="Open KeyDeck buttons",
            initialdir=os.path.join(os.path.expanduser("~"), "Documents"),
            filetypes=[("KeyDeck buttons", "*.keydeck *.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            new_pages = read_export_file(path)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"That file couldn't be read as KeyDeck buttons.\n\n{e}",
                                 parent=parent)
            return
        n = sum(len(pg["binds"]) for pg in new_pages)
        choice = messagebox.askyesnocancel(
            APP_NAME,
            f"This file has {n} button(s) on {len(new_pages)} page(s):\n"
            + "\n".join(f"  • {pg['name']} ({len(pg['binds'])})" for pg in new_pages[:12])
            + "\n\nYes = ADD these pages next to your current ones\n"
              "No = REPLACE all your current buttons with these\n"
              "Cancel = do nothing", parent=parent)
        if choice is None:
            return
        if choice is False and not messagebox.askyesno(
                APP_NAME, "Replace ALL your current buttons? This can't be undone.\n\n"
                "(Tip: Export your buttons first if you might want them back.)", parent=parent):
            return
        if self.editor:
            self.editor.close()
        if choice:  # add
            remap_page_ids(new_pages, {pg["id"] for pg in self.cfg["pages"]})
            existing = [pg["name"] for pg in self.cfg["pages"]]
            for pg in new_pages:
                pg["name"] = unique_name(pg["name"], existing)
                existing.append(pg["name"])
            first_new = len(self.cfg["pages"])
            self.cfg["pages"].extend(new_pages)
        else:  # replace
            self.cfg["pages"][:] = new_pages
            first_new = 0
        cleared = self._clear_hotkey_clashes(new_pages)
        self._set_page(first_new)
        self.apply()
        msg = f"Imported {n} button(s)."
        if cleared:
            msg += (f"\n\n{cleared} hotkey(s) were removed because you already use those keys. "
                    "Right-click a button to give it a new one.")
        messagebox.showinfo(APP_NAME, msg, parent=parent)

    def _clear_hotkey_clashes(self, new_pages):
        """Imported buttons lose any hotkey that's already taken."""
        new_ids = {id(b) for pg in new_pages for b in pg["binds"]}
        taken = {norm_hotkey(self.cfg["panel"].get("toggle_hotkey"))}
        for _, _, b in self.all_binds():
            if id(b) not in new_ids and b.get("hotkey"):
                taken.add(norm_hotkey(b["hotkey"]))
        cleared = 0
        for pg in new_pages:
            for b in pg["binds"]:
                hk = norm_hotkey(b.get("hotkey"))
                if hk and (hk in taken or not valid_hotkey(hk)):
                    b["hotkey"] = ""
                    cleared += 1
                elif hk:
                    taken.add(hk)
        return cleared

    def open_settings(self):
        if self.settings and self.settings.win.winfo_exists():
            force_foreground(self.settings.win)
            return
        self.settings = SettingsWindow(self)

    def apply(self):
        save_config(self.cfg)
        self.register_hotkeys()
        self.panel.rebuild()

    def quit(self):
        log("Quit")
        # Safety net: if anything hangs while shutting down, force the process closed.
        t = threading.Timer(2.0, lambda: os._exit(0))
        t.daemon = True
        t.start()
        try:
            for w in list(self.root.winfo_children()):
                if isinstance(w, tk.Toplevel):
                    w.destroy()
        except Exception:
            pass
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        self.root.quit()

    def run(self):
        log("Running")
        self.root.mainloop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def hide_console():
    """If KeyDeck was started in a way that opened a black console window
    (like double-clicking keydeck.py), hide it. run_debug.bat keeps it visible."""
    if os.environ.get("KEYDECK_DEBUG") == "1":
        return
    try:
        k = ctypes.windll.kernel32
        k.GetConsoleWindow.restype = ctypes.c_void_p
        hwnd = k.GetConsoleWindow()
        if hwnd:
            # only hide a console that belongs to KeyDeck alone, never someone's open terminal
            procs = (ctypes.c_ulong * 4)()
            if k.GetConsoleProcessList(procs, 4) <= 1:
                user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def main():
    hide_console()
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    if self_install_if_needed():
        return
    remove_old_keydrop()

    if already_running():
        log("Another KeyDeck is running; asking it to show itself")
        signal_show()
        time.sleep(1.0)
        if not show_requested():
            log("The running copy answered and showed its window. Exiting.")
            return
        # Nobody answered: the other copy is stuck. Close it and start fresh.
        log("Running copy didn't answer; closing it")
        if kill_other_copies():
            time.sleep(1.0)
        if already_running():
            user32.MessageBoxW(
                None,
                "Another copy of KeyDeck is stuck in the background.\n\n"
                "Open Task Manager (Ctrl+Shift+Esc), end every KeyDeck.exe task, "
                "then open KeyDeck again.",
                APP_NAME, 0x30)
            return

    try:
        App().run()
    except Exception:
        fatal("KeyDeck couldn't start:", traceback.format_exc())
    log("Exited")
    os._exit(0)  # make sure no background thread keeps KeyDeck alive


def selftest():
    """Used by the automatic GitHub build to prove the .exe really works
    before it's published. Returns 0 if everything checks out."""
    problems = []
    try:
        assert expand_text("{a|a}") == "a"
        assert expand_text("x {clipboard}", clip="Steve") == "x Steve"
        assert expand_text("keep {this}") == "keep {this}"
        assert version_tuple("v1.10.2") > version_tuple("1.9.9")
    except Exception:
        problems.append("text commands: " + traceback.format_exc())
    try:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        assert cfg["pages"] and cfg["pages"][0]["binds"]
    except Exception:
        problems.append("config: " + traceback.format_exc())
    try:
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), "keydeck_selftest.keydeck")
        save_export_file(tmp, [{"name": "Test", "binds": [{**DEFAULT_BIND, "label": "x", "text": "hi"}]}])
        back = read_export_file(tmp)
        os.remove(tmp)
        assert back[0]["name"] == "Test" and back[0]["binds"][0]["text"] == "hi"
        assert unique_name("Main", ["Main", "Main (2)"]) == "Main (3)"
        pgs = [{"name": "A", "id": "same", "binds": [{**DEFAULT_BIND, "action": "page", "goto": "same"}]}]
        remap_page_ids(pgs, {"same"})
        assert pgs[0]["id"] != "same" and pgs[0]["binds"][0]["goto"] == pgs[0]["id"]
        assert clean_bind({"action": "weird"})["action"] == "text"
        assert plan_text("hi{enter}/tp {clipboard}{Enter}", clip="Bob{enter}") == [
            ("text", "hi"), ("enter",), ("text", "/tp Bob{enter}"), ("enter",)]
        assert plan_text("a{wait 1.5}b") == [("text", "a"), ("wait", 1.5), ("text", "b")]
    except Exception:
        problems.append("backup/share: " + traceback.format_exc())
    try:
        r = tk.Tk()
        r.withdraw()
        ttk.Button(r, text="ok")
        from PIL import ImageTk
        ImageTk.PhotoImage(make_icon_image())
        r.destroy()
    except Exception:
        problems.append("window toolkit: " + traceback.format_exc())
    try:
        keyboard.parse_hotkey("ctrl+alt+1")
        import pystray._win32  # noqa: F401
        import ssl, urllib.request  # noqa: F401,E401  (needed by the updater)
        ssl.create_default_context()
    except Exception:
        problems.append("hotkeys/tray: " + traceback.format_exc())
    for p in problems:
        log("SELFTEST FAIL " + p)
    log(f"SELFTEST {'FAILED' if problems else 'OK'} v{VERSION}")
    return 1 if problems else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        code = selftest()
        if _log_file:
            _log_file.flush()
        os._exit(code)
    main()
