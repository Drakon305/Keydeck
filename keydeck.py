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
VERSION = "1.17.3"
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
                "enter": False, "enter_before": False, "enabled": True, "color": TILE,
                "action": "text",  # "text" = post text, "page" = jump to another page
                "goto": "",        # id of the page to jump to (for action "page")
                # action "reply" = a Discord slash command filled in for you:
                "cmd": "/reply", "opt1": "", "opt2": "", "opt3": ""}
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
        "no_focus": True,  # clicking KeyDeck doesn't take focus away from your game
        "toggle_hotkey": "ctrl+alt+p",
        "beta": False,  # True = get test versions before everyone else
        "submitter": "",  # name shown on Library submissions
        "slash_speed": 1.0,  # multiplies the pauses in slash-command buttons
        "admin_token": "",  # Library admin key (only on the admin's PC)
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
                              "pack": pg.get("pack") if isinstance(pg.get("pack"), str) else None,
                              "pack_sha": pg.get("pack_sha") if isinstance(pg.get("pack_sha"), str) else None,
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
    p["no_focus"] = bool(p.get("no_focus", True))
    p["beta"] = bool(p["beta"])
    try:
        p["slash_speed"] = max(0.5, min(3.0, float(p["slash_speed"])))
    except Exception:
        p["slash_speed"] = 1.0
    for key in ("submitter", "admin_token"):
        if not isinstance(p.get(key), str):
            p[key] = ""
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
    if b.get("action") not in ("text", "page", "reply"):
        b["action"] = "text"
    for k in ("label", "hotkey", "text", "goto", "cmd", "opt1", "opt2", "opt3"):
        if not isinstance(b.get(k), str):
            b[k] = ""
    if b["mode"] not in ("paste", "type", "copy"):
        b["mode"] = "paste"
    b["enter"] = bool(b["enter"])
    b["enter_before"] = bool(b.get("enter_before"))
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
    return pages_from_data(data)


def pages_to_data(pages, description=""):
    data = {"keydeck_export": EXPORT_FORMAT, "app_version": VERSION,
            "pages": [{"name": pg["name"], "id": pg.get("id"),
                       "binds": [dict(b) for b in pg["binds"]]} for pg in pages]}
    if description:
        data["description"] = description
    return data


def pages_from_data(data):
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


# ---- button library -------------------------------------------------------
# Ready-made button sets live in the "packs" folder of the GitHub repo.
# Each .keydeck file there (made with "Export this page") is one pack.

LIBRARY_DIR = "packs"


def fetch_library():
    """[{key, name, sha, url}] for every pack in the repo's packs folder."""
    with _http_get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{LIBRARY_DIR}") as r:
        items = json.load(r)
    packs = []
    for it in items if isinstance(items, list) else []:
        name = str(it.get("name", ""))
        if it.get("type") == "file" and name.lower().endswith(".keydeck") and it.get("download_url"):
            packs.append({"key": name, "name": name[:-len(".keydeck")],
                          "sha": it.get("sha", ""), "url": it["download_url"]})
    return sorted(packs, key=lambda x: x["name"].lower())


def download_pack(pack, token=None):
    """The pages inside one library pack, tagged with where they came from.
    With the admin key it reads the file fresh from GitHub, so edits show up right away."""
    import tempfile
    import base64
    import urllib.parse
    if token:
        data = github_api("GET", f"/repos/{GITHUB_REPO}/contents/"
                          + urllib.parse.quote(f"{LIBRARY_DIR}/{pack['key']}") + "?ref=main", token)
        raw = base64.b64decode(data.get("content", ""))
        pack["sha"] = data.get("sha", pack.get("sha"))
    else:
        with _http_get(pack["url"]) as r:
            raw = r.read()
    if len(raw) > 2_000_000:
        raise ValueError("That pack is too big.")
    tmp = os.path.join(tempfile.gettempdir(), "keydeck_pack.keydeck")
    with open(tmp, "wb") as f:
        f.write(raw)
    try:
        pages = read_export_file(tmp)
        with open(tmp, "r", encoding="utf-8-sig") as f:
            desc = json.load(f).get("description", "")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    for pg in pages:
        pg["pack"], pg["pack_sha"] = pack["key"], pack["sha"]
    return pages, (desc if isinstance(desc, str) else "")


# ---- library submissions ---------------------------------------------------
# Mods send a page to the Library with "Submit to Library". It arrives as a
# GitHub issue in the repo. The admin approves it from inside KeyDeck, which
# saves it into the packs folder so it appears in everyone's Library.

SUBMISSION_TAG = "[KeyDeck submission]"

try:  # written by the GitHub build from a repository secret; not in the source code
    from keydeck_secrets import SUBMIT_KEY as _SUBMIT_KEY
except Exception:
    _SUBMIT_KEY = ""


def submit_token():
    """The submit-only key built into this copy (can only create submissions)."""
    import base64
    try:
        return base64.b64decode(_SUBMIT_KEY.encode())[::-1].decode() if _SUBMIT_KEY else ""
    except Exception:
        return ""


def github_api(method, path, token=None, body=None, timeout=20):
    import urllib.request
    import urllib.error
    url = path if path.startswith("http") else f"https://api.github.com{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "User-Agent": f"KeyDeck/{VERSION}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read()).get("message", "")
        except Exception:
            pass
        raise RuntimeError(f"GitHub said {e.code}: {detail or e.reason}") from None


def safe_pack_filename(name):
    clean = re.sub(r"[^\w \-().']+", "", name or "").strip()[:50]
    return (clean or "Button set") + ".keydeck"


def make_submission(name, submitter, description, pages):
    """(title, body) of the issue that carries a submission."""
    payload = json.dumps(pages_to_data(pages, description), ensure_ascii=False, separators=(",", ":"))
    n = sum(len(pg["binds"]) for pg in pages)
    body = (f"**Set name:** {name}\n**Submitted by:** {submitter or 'someone'}\n**Buttons:** {n}\n\n"
            f"{description}\n\n"
            "Approve or reject this from KeyDeck (Library window, admin only).\n\n"
            f"<!-- KeyDeck data - do not edit below this line -->\n```keydeck\n{payload}\n```\n")
    if len(body) > 60000:
        raise ValueError("That page is too big to submit. Try splitting it into two pages.")
    return f"{SUBMISSION_TAG} {name}", body


def parse_submission(issue):
    title = issue.get("title") or ""
    body = issue.get("body") or ""
    m = re.search(r"```keydeck\n(.*?)\n```", body, re.S)
    if not title.startswith(SUBMISSION_TAG) or not m:
        raise ValueError("not a KeyDeck submission")
    data = json.loads(m.group(1))
    who = re.search(r"\*\*Submitted by:\*\* *(.+)", body)
    return {"number": issue.get("number"), "url": issue.get("html_url", ""),
            "name": title[len(SUBMISSION_TAG):].strip() or "Untitled set",
            "submitter": who.group(1).strip() if who else "someone",
            "description": data.get("description", "") if isinstance(data.get("description"), str) else "",
            "pages": pages_from_data(data)}


def submit_to_library(name, submitter, description, pages):
    token = submit_token()
    if not token:
        raise RuntimeError("Submissions aren't set up in this copy of KeyDeck yet.")
    title, body = make_submission(name, submitter, description, pages)
    return github_api("POST", f"/repos/{GITHUB_REPO}/issues", token, {"title": title, "body": body})


def check_admin_token(token):
    data = github_api("GET", f"/repos/{GITHUB_REPO}", token)
    return bool((data.get("permissions") or {}).get("push"))


def list_submissions(token):
    issues = github_api("GET", f"/repos/{GITHUB_REPO}/issues?state=open&per_page=50", token)
    subs = []
    for it in issues if isinstance(issues, list) else []:
        if it.get("pull_request") or not str(it.get("title", "")).startswith(SUBMISSION_TAG):
            continue
        try:
            subs.append(parse_submission(it))
        except Exception as e:
            log(f"Skipped unreadable submission #{it.get('number')}: {e}")
    return subs


def _close_issue(token, number, comment, reason):
    github_api("POST", f"/repos/{GITHUB_REPO}/issues/{number}/comments", token, {"body": comment})
    github_api("PATCH", f"/repos/{GITHUB_REPO}/issues/{number}", token,
               {"state": "closed", "state_reason": reason})


def save_pack_file(token, pack, pages, description, message):
    """Write a library pack back to GitHub (admin only)."""
    import base64
    import urllib.parse
    content = json.dumps(pages_to_data(pages, description), indent=2, ensure_ascii=False)
    path = urllib.parse.quote(f"{LIBRARY_DIR}/{pack['key']}")
    github_api("PUT", f"/repos/{GITHUB_REPO}/contents/{path}", token,
               {"message": message, "sha": pack["sha"],
                "content": base64.b64encode(content.encode("utf-8")).decode()})


def delete_pack_file(token, pack, message):
    import urllib.parse
    path = urllib.parse.quote(f"{LIBRARY_DIR}/{pack['key']}")
    github_api("DELETE", f"/repos/{GITHUB_REPO}/contents/{path}", token,
               {"message": message, "sha": pack["sha"]})


def approve_submission(token, sub, filename, existing_sha=None):
    """Publish a submission into the packs folder, then close its issue."""
    import base64
    import urllib.parse
    content = json.dumps(pages_to_data(sub["pages"], sub["description"]), indent=2, ensure_ascii=False)
    body = {"message": f"Library: add {filename} (from {sub['submitter']})",
            "content": base64.b64encode(content.encode("utf-8")).decode()}
    if existing_sha:
        body["sha"] = existing_sha
    path = urllib.parse.quote(f"{LIBRARY_DIR}/{filename}")
    github_api("PUT", f"/repos/{GITHUB_REPO}/contents/{path}", token, body)
    _close_issue(token, sub["number"], f"Approved and added to the Library as **{filename}**. Thanks!",
                 "completed")


def reject_submission(token, sub):
    _close_issue(token, sub["number"], "Not added to the Library this time.", "not_planned")


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


# {enter} {tab} {wait 2} - round brackets work too: (enter) (tab) (wait 2)
# {key f1} / {key ctrl+v} presses any key or combo
_STEP_RE = re.compile(r"[{(]\s*(enter|tab|wait\s*:?\s*(\d+(?:\.\d+)?)|key\s+([a-z0-9+ ]+?))\s*[})]",
                      re.IGNORECASE)


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
        word = m.group(1).lower()
        if word.startswith("enter"):
            steps.append(("enter",))
        elif word.startswith("tab"):
            steps.append(("tab",))
        elif word.startswith("key"):
            steps.append(("key", m.group(3).strip().lower()))
        else:
            steps.append(("wait", min(30.0, float(m.group(2)))))
        pos = m.end()
    chunk = text[pos:]
    if chunk:
        steps.append(("text", _CLIP_RE.sub(lambda _: clip or "", chunk)))
    return steps


SLASH_SPEEDS = [("Fast", 0.7), ("Normal", 1.0), ("Slow", 1.5), ("Very slow", 2.0), ("Super slow", 3.0)]


def slash_options(b):
    return [b.get(k, "").strip() for k in ("opt1", "opt2", "opt3") if b.get(k, "").strip()]


def slash_plan(b, speed=1.0, clip=None):
    """Steps for a Discord slash-command button: type the command, pick it, then
    type each option and pick it from Discord's list, then send.
    Same timing as the hand-made recipe that worked:
    /reply{wait 1}{tab}Cat{wait 1.5}{tab}Resp{wait 2}{tab}{wait 0.5}{enter}"""
    def flat(t):  # allow {a|b} and {clipboard} inside options
        return "".join(st[1] for st in plan_text(t, clip) if st[0] == "text")
    cmd = flat(b.get("cmd") or "/reply").strip()
    if not cmd.startswith("/"):
        cmd = "/" + cmd
    steps = [("text", cmd), ("wait", round(1.0 * speed, 2))]
    opts = slash_options(b)
    for n, opt in enumerate(opts):
        last = n == len(opts) - 1
        steps += [("tab",), ("text", flat(opt)), ("wait", round((2.0 if last else 1.5) * speed, 2))]
    steps += [("tab",), ("wait", round(0.5 * speed, 2)), ("enter",)]
    return steps


def describe_plan(steps):
    """Readable preview of what a button will do."""
    out = []
    for st in steps:
        if st[0] == "text":
            out.append(st[1])
        elif st[0] == "enter":
            out.append(" [Enter]\n")
        elif st[0] == "tab":
            out.append(" [Tab] ")
        elif st[0] == "key":
            out.append(f" [{st[1].upper()}] ")
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


def _exe_url(release):
    asset = next((a for a in release.get("assets", [])
                  if str(a.get("name", "")).lower() == "keydeck.exe"), None)
    return (asset or {}).get("browser_download_url")


def fetch_latest_release(beta=False):
    """(tag, exe_download_url, notes, is_beta) for the newest version this copy should get.

    Everyone gets the newest normal release. Testers (beta=True) also get
    versions still marked "pre-release" on GitHub, i.e. not released to everyone yet."""
    if not beta:
        with _http_get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest") as r:
            data = json.load(r)
        return data.get("tag_name", ""), _exe_url(data), data.get("body") or "", False
    with _http_get(f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=20") as r:
        releases = json.load(r)
    usable = [x for x in releases if not x.get("draft") and _exe_url(x)]
    if not usable:
        return "", None, "", False
    best = max(usable, key=lambda x: version_tuple(x.get("tag_name", "")))
    return best.get("tag_name", ""), _exe_url(best), best.get("body") or "", bool(best.get("prerelease"))


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


GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000
try:
    _GetWL = user32.GetWindowLongPtrW
    _SetWL = user32.SetWindowLongPtrW
except AttributeError:  # 32-bit Windows
    _GetWL = user32.GetWindowLongW
    _SetWL = user32.SetWindowLongW
_GetWL.restype = ctypes.c_ssize_t
_GetWL.argtypes = [ctypes.c_void_p, ctypes.c_int]
_SetWL.restype = ctypes.c_ssize_t
_SetWL.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]


def set_no_activate(win, on):
    """With on=True, clicking the window doesn't take focus away from the game
    or app you were in (like the Windows on-screen keyboard). Keeps the
    taskbar button. Returns True if the style had to be changed."""
    hwnd = get_hwnd(win)
    if not hwnd:
        return False
    ex = _GetWL(hwnd, GWL_EXSTYLE)
    new = (ex | WS_EX_NOACTIVATE | WS_EX_APPWINDOW) if on else (ex & ~WS_EX_NOACTIVATE)
    if new != ex:
        _SetWL(hwnd, GWL_EXSTYLE, new)
        return True
    return False


user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]


def set_topmost_quietly(win, on):
    """Stay on top / stop staying on top without grabbing focus from the game."""
    user32.SetWindowPos(get_hwnd(win), ctypes.c_void_p(-1 if on else -2), 0, 0, 0, 0,
                        0x0001 | 0x0002 | 0x0010)  # NOSIZE | NOMOVE | NOACTIVATE


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


user32.WindowFromPoint.argtypes = [_POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p
user32.GetAsyncKeyState.restype = ctypes.c_short


def raise_quietly(win):
    """Bring the window in front of other windows without taking focus."""
    user32.SetWindowPos(get_hwnd(win), ctypes.c_void_p(0), 0, 0, 0, 0,
                        0x0001 | 0x0002 | 0x0010)  # HWND_TOP; NOSIZE | NOMOVE | NOACTIVATE


def mouse_down_on(win):
    """True while the left mouse button is held over this window (title bar included)."""
    if not (user32.GetAsyncKeyState(0x01) & 0x8000):
        return False
    pt = _POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    w = user32.WindowFromPoint(pt)
    return bool(w) and user32.GetAncestor(w, 2) == get_hwnd(win)


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
        self._bar_btn(bar, "📦 Library", app.open_library).pack(side="left")
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
        m.add_command(label="Submit to Library…", command=lambda: self.app.submit_page(k))
        m.add_command(label="Import buttons…", command=lambda: self.app.import_pages())
        m.add_command(label="Move left", command=lambda: self.app.move_page(k, -1),
                      state="normal" if k > 0 else "disabled")
        m.add_command(label="Move right", command=lambda: self.app.move_page(k, 1),
                      state="normal" if k < n - 1 else "disabled")
        m.add_separator()
        m.add_command(label="Delete page", command=lambda: self.app.delete_page(k),
                      state="normal" if n > 1 else "disabled")
        self._popup(m, e)

    def apply_no_focus(self):
        try:
            set_no_activate(self.win, self.app.cfg["panel"]["no_focus"])
        except Exception:
            log("no_focus failed:\n" + traceback.format_exc())

    def _popup(self, m, e):
        # right-click menus need KeyDeck focused to work (and close) properly
        force_foreground(self.win)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    # build the button grid
    def rebuild(self):
        self._build_tabs()
        p = self.app.cfg["panel"]
        self.win.attributes("-alpha", p["opacity"])
        if p["no_focus"]:
            self.apply_no_focus()
            set_topmost_quietly(self.win, p["always_on_top"])
        else:
            self.apply_no_focus()
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
        elif b.get("action") == "reply":
            opts = slash_options(b)
            title = b["label"] or (opts[-1] if opts else b.get("cmd") or "(empty)")
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
        elif b.get("action") == "reply":
            sub.append((b.get("cmd") or "/reply").strip())
        elif b.get("mode") == "copy":
            sub.append("📋 copy")
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
            w.bind("<Button-3>", lambda e, i=i: self._button_menu(e, i))  # right-click menu
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    def _button_menu(self, e, i):
        m = tk.Menu(self.win, tearoff=0)
        m.add_command(label="Edit…", command=lambda: self.app.edit_bind(i))
        m.add_command(label="Duplicate", command=lambda: self.app.duplicate_bind(i))
        m.add_command(label="Submit to Library…", command=lambda: self.app.submit_button(i))
        m.add_separator()
        m.add_command(label="Delete", command=lambda: self.app.delete_bind(i))
        self._popup(m, e)

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
        p = self.app.cfg["panel"]
        if p["no_focus"]:  # bring it up without taking focus from the game
            hwnd = get_hwnd(self.win)
            if self.win.state() != "normal":
                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
            set_topmost_quietly(self.win, True)
            if not p["always_on_top"]:
                self.win.after(200, lambda: set_topmost_quietly(self.win, False))
            return
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
        d.geometry("580x600")
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

        self.text_label = ttk.Label(f, text="Text to post")
        self.text_label.grid(row=2, column=0, sticky="nw", pady=3)
        tf = self.text_frame = ttk.Frame(f)
        tf.grid(row=2, column=1, columnspan=2, sticky="nsew", pady=3)
        self.text = tk.Text(tf, height=7, wrap="word", font=("Segoe UI", 10), undo=True)
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", b["text"])
        tip = ttk.Frame(tf)
        tip.pack(fill="x", pady=(3, 0))
        ttk.Label(tip, foreground="#666666", font=("Segoe UI", 8),
                  text="{a|b} random  {clipboard} copied  {enter}  {tab}  {key f1}  {wait 1} pause"
                  ).pack(side="left")
        ttk.Button(tip, text="Preview", command=self.preview).pack(side="right")

        sf = self.slash_frame = ttk.Frame(f)
        sf.grid(row=2, column=1, columnspan=2, sticky="nsew", pady=3)
        sf.columnconfigure(1, weight=1)
        self.cmd = tk.StringVar(value=b.get("cmd") or "/reply")
        self.opts = [tk.StringVar(value=b.get(k, "")) for k in ("opt1", "opt2", "opt3")]
        rows = [("Command", self.cmd, "e.g. /reply"),
                ("1st option", self.opts[0], "e.g. General Support (category)"),
                ("2nd option", self.opts[1], "e.g. Raid Not Spawning (response)"),
                ("3rd option", self.opts[2], "optional - leave empty if the command has 2")]
        for r_, (lbl, var, hint) in enumerate(rows):
            ttk.Label(sf, text=lbl).grid(row=r_ * 2, column=0, sticky="w", padx=(0, 8))
            ttk.Entry(sf, textvariable=var).grid(row=r_ * 2, column=1, sticky="ew", pady=(2, 0))
            ttk.Label(sf, text=hint, foreground="#888888", font=("Segoe UI", 8)
                      ).grid(row=r_ * 2 + 1, column=1, sticky="w")
        stip = ttk.Frame(sf)
        stip.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(stip, foreground="#666666", font=("Segoe UI", 8), wraplength=330, justify="left",
                  text="Type the option names as they appear in Discord's list. "
                       "Too fast or slow? Settings > Slash command speed.").pack(side="left")
        ttk.Button(stip, text="Preview", command=self.preview).pack(side="right")

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
        ttk.Radiobutton(act, text="Post text", variable=self.action, value="text",
                        command=self._action_changed).pack(side="left")
        ttk.Radiobutton(act, text="Slash command", variable=self.action, value="reply",
                        command=self._action_changed).pack(side="left", padx=(10, 0))
        ttk.Radiobutton(act, text="Go to page:", variable=self.action, value="page",
                        command=self._action_changed).pack(side="left", padx=(10, 4))
        self._page_ids = [pg["id"] for pg in app.cfg["pages"]]
        self.goto_box = ttk.Combobox(act, values=[pg["name"] for pg in app.cfg["pages"]],
                                     state="readonly", width=18)
        if b.get("goto") in self._page_ids:
            self.goto_box.current(self._page_ids.index(b["goto"]))
        self.goto_box.pack(side="left")
        self.goto_box.bind("<<ComboboxSelected>>",
                           lambda e: (self.action.set("page"), self._action_changed()))

        self.mode = tk.StringVar(value=b["mode"])
        ttk.Radiobutton(opts, text="Paste it (fast, works almost everywhere)",
                        variable=self.mode, value="paste").pack(anchor="w")
        ttk.Radiobutton(opts, text="Type it out (for apps that block pasting)",
                        variable=self.mode, value="type").pack(anchor="w")
        ttk.Radiobutton(opts, text="Copy it to the clipboard only (types nothing - e.g. a SteamID)",
                        variable=self.mode, value="copy").pack(anchor="w")
        self.enter_before = tk.BooleanVar(value=bool(b.get("enter_before")))
        ttk.Checkbutton(opts, text="Press Enter before (opens game chat first)",
                        variable=self.enter_before).pack(anchor="w")
        self.enter = tk.BooleanVar(value=b["enter"])
        ttk.Checkbutton(opts, text="Press Enter after (auto-send in chats)",
                        variable=self.enter).pack(anchor="w")
        self.enabled = tk.BooleanVar(value=b["enabled"])
        ttk.Checkbutton(opts, text="Enabled", variable=self.enabled).pack(anchor="w")

        bb = ttk.Frame(f)
        bb.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        if editing:
            ttk.Button(bb, text="Delete", command=self.delete).pack(side="left")
            ttk.Button(bb, text="Duplicate", command=self.duplicate).pack(side="left", padx=(6, 0))
            ttk.Button(bb, text="◀ Move", command=lambda: self.move(-1)).pack(side="left", padx=(6, 0))
            ttk.Button(bb, text="Move ▶", command=lambda: self.move(1)).pack(side="left", padx=(4, 0))
        ttk.Button(bb, text="Cancel", command=self.close).pack(side="right")
        ttk.Button(bb, text="Save", command=self.save).pack(side="right", padx=(0, 6))

        self._show_fields()
        force_foreground(d)
        d.after(80, lambda: force_foreground(d) if d.winfo_exists() else None)
        (self.text if editing else self.label_entry).focus_set()

    def _show_fields(self):
        """Text box for normal buttons, command fields for slash-command buttons."""
        if self.action.get() == "reply":
            self.text_frame.grid_remove()
            self.slash_frame.grid()
            self.text_label.config(text="Slash command")
        else:
            self.slash_frame.grid_remove()
            self.text_frame.grid()
            self.text_label.config(text="Text to post" if self.action.get() == "text" else "Text (not used)")

    def _action_changed(self):
        self._show_fields()
        if self.action.get() == "page" and self.goto_box.current() < 0:
            self.goto_box.focus_set()
            self.goto_box.event_generate("<Down>")  # open the list so you can pick

    def _slash_data(self):
        return {"cmd": self.cmd.get().strip() or "/reply",
                **{f"opt{n + 1}": v.get().strip() for n, v in enumerate(self.opts)}}

    def preview(self):
        if self.action.get() == "reply":
            speed = self.app.cfg["panel"]["slash_speed"]
            plan = describe_plan(slash_plan(self._slash_data(), speed))
            messagebox.showinfo(APP_NAME, "KeyDeck will type it out like this:\n\n" + plan, parent=self.win)
            return
        raw = self.text.get("1.0", "end-1c")
        samples = "\n\n".join(f"{n}) {describe_plan(plan_text(raw))}" for n in range(1, 4))
        messagebox.showinfo(APP_NAME, f"Three sample results:\n\n{samples}", parent=self.win)

    def duplicate(self):
        self.close()
        self.app.duplicate_bind(self.index)

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
        elif action == "reply":
            sd = self._slash_data()
            if not any(sd[k] for k in ("opt1", "opt2", "opt3")):
                err = "Fill in at least the 1st option (for /reply: the category)."
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
                "enter_before": self.enter_before.get(),
                "enabled": self.enabled.get(), "color": self.color,
                "action": action, "goto": goto, **self._slash_data()}
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
        w.geometry("480x620")
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
        self.no_focus = tk.BooleanVar(value=p["no_focus"])
        ttk.Checkbutton(f, text="Clicking KeyDeck doesn't take focus from your game",
                        variable=self.no_focus).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        ttk.Label(f, text="Slash command speed").grid(row=r, column=0, sticky="w", padx=(0, 8))
        names = [n for n, _ in SLASH_SPEEDS]
        cur = min(SLASH_SPEEDS, key=lambda x: abs(x[1] - p["slash_speed"]))[0]
        self.slash_speed = ttk.Combobox(f, values=names, state="readonly", width=12)
        self.slash_speed.set(cur)
        self.slash_speed.grid(row=r, column=1, sticky="w", pady=3)
        r += 1
        self.show_hotkeys = tk.BooleanVar(value=p["show_hotkeys"])
        ttk.Checkbutton(f, text="Show hotkeys on buttons", variable=self.show_hotkeys
                        ).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        self.startup = tk.BooleanVar(value=get_startup())
        ttk.Checkbutton(f, text="Start KeyDeck with Windows", variable=self.startup,
                        command=self.toggle_startup).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        self.beta = tk.BooleanVar(value=p["beta"])
        ttk.Checkbutton(f, text="Tester: get new versions early (beta)", variable=self.beta,
                        command=self.toggle_beta).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        adm = ttk.Frame(f)
        adm.grid(row=r, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.admin_label = ttk.Label(adm, text=self._admin_text())
        self.admin_label.pack(side="left")
        ttk.Button(adm, text="Library admin key…", command=self.set_admin).pack(side="left", padx=(8, 0))
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

    def _admin_text(self):
        return "Library admin: ON" if self.app.cfg["panel"]["admin_token"] else "Library admin: off"

    def set_admin(self):
        self.app.set_admin_key(parent=self.win, then=lambda: self.admin_label.winfo_exists()
                               and self.admin_label.config(text=self._admin_text()))

    def toggle_beta(self):
        self.app.cfg["panel"]["beta"] = self.beta.get()
        save_config(self.app.cfg)
        if self.beta.get():
            self.app.check_for_updates(manual=True)

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
            slash_speed=dict(SLASH_SPEEDS).get(self.slash_speed.get(), 1.0),
            always_on_top=self.on_top.get(),
            no_focus=self.no_focus.get(),
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




class LibraryItemEditor:
    """Admin-only: change a button that's already in the shared Library."""

    def __init__(self, lib, it):
        self.lib, self.it = lib, it
        b = {**DEFAULT_BIND, **it["bind"]}
        d = self.win = tk.Toplevel(lib.win)
        d.title("Edit Library button")
        d.geometry("520x470")
        d.minsize(440, 400)
        d.attributes("-topmost", True)
        f = ttk.Frame(d, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        f.rowconfigure(2, weight=1)
        ttk.Label(f, foreground="#c0392b", wraplength=480, justify="left",
                  text=f'In "{it["group"]}". Saving changes it in everyone\'s Library right away. '
                       "Copies people already added aren't changed.").grid(row=0, column=0, columnspan=2,
                                                                         sticky="w", pady=(0, 8))
        ttk.Label(f, text="Button name").grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.label = tk.StringVar(value=b["label"])
        ttk.Entry(f, textvariable=self.label).grid(row=1, column=1, sticky="ew", pady=3)
        self.action = b["action"]
        if self.action == "reply":
            sf = ttk.Frame(f)
            sf.grid(row=2, column=1, sticky="nsew", pady=3)
            sf.columnconfigure(1, weight=1)
            ttk.Label(f, text="Slash command").grid(row=2, column=0, sticky="nw", pady=3)
            self.cmd = tk.StringVar(value=b["cmd"] or "/reply")
            self.opts = [tk.StringVar(value=b[k]) for k in ("opt1", "opt2", "opt3")]
            for r_, (lbl, var) in enumerate([("Command", self.cmd), ("1st option", self.opts[0]),
                                             ("2nd option", self.opts[1]), ("3rd option", self.opts[2])]):
                ttk.Label(sf, text=lbl).grid(row=r_, column=0, sticky="w", padx=(0, 8))
                ttk.Entry(sf, textvariable=var).grid(row=r_, column=1, sticky="ew", pady=2)
        else:
            ttk.Label(f, text="Text to post").grid(row=2, column=0, sticky="nw", pady=3)
            self.text = tk.Text(f, height=8, wrap="word", font=("Segoe UI", 10), undo=True)
            self.text.grid(row=2, column=1, sticky="nsew", pady=3)
            self.text.insert("1.0", b["text"])
        ttk.Label(f, text="Color").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.color = b["color"]
        sw = tk.Frame(f)
        sw.grid(row=3, column=1, sticky="w", pady=(6, 0))
        self.swatches = []
        for c in SWATCHES:
            s_ = tk.Label(sw, bg=c, width=3, height=1, cursor="hand2", bd=3, relief="flat")
            s_.pack(side="left", padx=2)
            s_.bind("<Button-1>", lambda e, c=c: self.pick_color(c))
            self.swatches.append((c, s_))
        self.pick_color(self.color)
        opts = ttk.Frame(f)
        opts.grid(row=4, column=1, sticky="w", pady=(8, 0))
        self.mode = tk.StringVar(value=b["mode"])
        self.enter = tk.BooleanVar(value=b["enter"])
        self.enter_before = tk.BooleanVar(value=bool(b.get("enter_before")))
        if self.action != "reply":
            ttk.Radiobutton(opts, text="Paste it", variable=self.mode, value="paste").pack(anchor="w")
            ttk.Radiobutton(opts, text="Type it out", variable=self.mode, value="type").pack(anchor="w")
            ttk.Radiobutton(opts, text="Copy to clipboard only", variable=self.mode, value="copy").pack(anchor="w")
            ttk.Checkbutton(opts, text="Press Enter before", variable=self.enter_before).pack(anchor="w")
            ttk.Checkbutton(opts, text="Press Enter after", variable=self.enter).pack(anchor="w")
        bb = ttk.Frame(f)
        bb.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bb, text="Cancel", command=d.destroy).pack(side="right")
        ttk.Button(bb, text="Save to Library", command=self.save).pack(side="right", padx=(0, 6))
        force_foreground(d)

    def pick_color(self, c):
        self.color = c
        for col, s_ in self.swatches:
            s_.config(relief="solid" if col == c else "flat")

    def save(self):
        nb = dict(self.it["bind"])
        nb.update(label=self.label.get().strip(), color=self.color, mode=self.mode.get(),
                  enter=self.enter.get(), enter_before=self.enter_before.get(), hotkey="")
        if self.action == "reply":
            nb.update(cmd=self.cmd.get().strip() or "/reply",
                      **{f"opt{n + 1}": v.get().strip() for n, v in enumerate(self.opts)})
            if not slash_options(nb):
                messagebox.showerror(APP_NAME, "Fill in at least the 1st option.", parent=self.win)
                return
        else:
            nb["text"] = self.text.get("1.0", "end-1c")
            if not nb["text"].strip():
                messagebox.showerror(APP_NAME, "The text can't be empty. Use Delete to remove the button.",
                                     parent=self.win)
                return
        self.win.destroy()
        self.lib.admin_save_item(self.it, nb)


class SubmitDialog:
    """Send one page to the Library admin for approval."""
    _last_sent = 0.0

    def __init__(self, app, page):
        self.app, self.page = app, page
        d = self.win = tk.Toplevel(app.root)
        d.title("Submit to Library")
        d.geometry("440x360")
        d.attributes("-topmost", True)
        f = ttk.Frame(d, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        f.rowconfigure(3, weight=1)
        n = len(page["binds"])
        what = (f'the button "{page["name"]}"' if n == 1 and page.get("_single")
                else f'the page "{page["name"]}" ({n} buttons)')
        ttk.Label(f, wraplength=410, justify="left",
                  text=f"Send {what} to the Library admin. "
                       "If it's approved, everyone can add it from their Library."
                  ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(f, text="Set name").grid(row=1, column=0, sticky="w")
        self.name = tk.StringVar(value=page["name"])
        ttk.Entry(f, textvariable=self.name).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(f, text="Your name").grid(row=2, column=0, sticky="w", padx=(0, 8))
        self.who = tk.StringVar(value=app.cfg["panel"]["submitter"])
        self.who_entry = ttk.Entry(f, textvariable=self.who)
        self.who_entry.grid(row=2, column=1, sticky="ew", pady=3)
        ttk.Label(f, text="What it's for").grid(row=3, column=0, sticky="nw", pady=3)
        self.desc = tk.Text(f, height=5, wrap="word", font=("Segoe UI", 10))
        self.desc.grid(row=3, column=1, sticky="nsew", pady=3)
        bb = ttk.Frame(f)
        bb.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bb, text="Cancel", command=d.destroy).pack(side="right")
        self.send_btn = ttk.Button(bb, text="Send", command=self.send)
        self.send_btn.pack(side="right", padx=(0, 6))
        force_foreground(d)
        (self.who_entry if not self.who.get() else self.desc).focus_set()

    def send(self):
        name = self.name.get().strip()[:40]
        who = self.who.get().strip()[:40]
        desc = self.desc.get("1.0", "end-1c").strip()[:1000]
        if not name or not who:
            messagebox.showerror(APP_NAME, "Fill in the set name and your name.", parent=self.win)
            return
        if time.time() - SubmitDialog._last_sent < 30:
            messagebox.showinfo(APP_NAME, "You just sent one - wait a few seconds before sending another.",
                                parent=self.win)
            return
        self.app.cfg["panel"]["submitter"] = who
        save_config(self.app.cfg)
        self.send_btn.config(state="disabled", text="Sending…")
        page = {"name": self.page["name"], "id": self.page.get("id"),
                "binds": [dict(b) for b in self.page["binds"]]}

        def worker():
            try:
                submit_to_library(name, who, desc, [page])
                err = None
            except Exception as e:
                err = str(e)

            def done():
                if not self.win.winfo_exists():
                    return
                if err:
                    self.send_btn.config(state="normal", text="Send")
                    messagebox.showerror(APP_NAME, f"Couldn't send it.\n\n{err}", parent=self.win)
                    return
                SubmitDialog._last_sent = time.time()
                messagebox.showinfo(APP_NAME, f'Sent! "{name}" is waiting for the Library admin to approve it.',
                                    parent=self.win)
                self.win.destroy()
            self.app.ui(done)

        threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------- library ---

class LibraryWindow:
    """One shared catalog of every button people have shared.
    Tick as many as you like (single buttons or whole groups) and add them in one go."""

    NEW_PAGE = "➕ New page…"

    def __init__(self, app):
        self.app = app
        w = self.win = tk.Toplevel(app.root)
        w.title("KeyDeck Button Library")
        w.geometry("640x580")
        w.minsize(480, 360)
        w.attributes("-topmost", True)
        w.protocol("WM_DELETE_WINDOW", self.close)

        top = ttk.Frame(w, padding=(12, 12, 12, 4))
        top.pack(fill="x")
        ttk.Label(top, text="Button Library", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(top, foreground="#555555", wraplength=600, justify="left",
                  text="Everything people have shared, in one place. Tick the buttons you want "
                       "(or a whole group), then add them to one of your pages.").pack(anchor="w")
        sr = ttk.Frame(top)
        sr.pack(fill="x", pady=(8, 0))
        ttk.Label(sr, text="🔍 Search").pack(side="left")
        self.search = tk.StringVar()
        ent = ttk.Entry(sr, textvariable=self.search)
        ent.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.search.trace_add("write", lambda *a: self._render())

        holder = ttk.Frame(w, padding=(12, 6, 12, 4))
        holder.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(holder, highlightthickness=0, bg="#ffffff")
        sb = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.list = tk.Frame(self.canvas, bg="#ffffff")
        self.list.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win_id = self.canvas.create_window((0, 0), window=self.list, anchor="nw")
        self.canvas.bind("<Configure>", self._on_resize)
        self._cols, self._resize_job = 4, None
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._wheel, add="+")

        self.hover = ttk.Label(w, foreground="#555555", font=("Segoe UI", 8), anchor="w",
                               text="Click tiles to select them. Hover a tile to read its full text.")
        self.hover.pack(fill="x", padx=14)
        bottom = ttk.Frame(w, padding=(12, 4, 12, 12))
        bottom.pack(fill="x")
        self.count_label = ttk.Label(bottom, text="0 selected", width=11)
        self.count_label.pack(side="left")
        ttk.Button(bottom, text="Clear", command=self.clear_selection).pack(side="left", padx=(0, 10))
        ttk.Label(bottom, text="Add to:").pack(side="left")
        self.target = ttk.Combobox(bottom, state="readonly", width=16)
        self.target.pack(side="left", padx=(4, 6))
        self.add_btn = ttk.Button(bottom, text="Add selected", command=self.add_selected)
        self.add_btn.pack(side="left")
        ttk.Button(bottom, text="Close", command=self.close).pack(side="right")
        ttk.Button(bottom, text="Refresh", command=self.load).pack(side="right", padx=(0, 6))

        self.items, self.packs, self.selected = [], [], set()
        self._subs = self._sub_err = self._err = None
        self._fill_targets()
        self.load()
        force_foreground(w)
        ent.focus_set()

    def _wheel(self, e):
        try:
            if self.win.winfo_exists() and str(e.widget).startswith(str(self.win)):
                self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        except tk.TclError:
            pass

    def _fill_targets(self):
        names = [pg["name"] for pg in self.app.cfg["pages"]]
        self.target["values"] = names + [self.NEW_PAGE]
        self.target.current(self.app.cfg["current_page"])

    def _section(self, text):
        tk.Label(self.list, text=text, bg="#ffffff", fg="#333333", anchor="w",
                 font=("Segoe UI", 9, "bold"), pady=6).pack(fill="x")

    def _message(self, text):
        tk.Label(self.list, text=text, bg="#ffffff", fg="#555555", wraplength=560,
                 justify="left", pady=14).pack(anchor="w")

    # ---- loading ----
    def load(self):
        for c in self.list.winfo_children():
            c.destroy()
        self._message("Loading the library…")
        token = self.app.cfg["panel"]["admin_token"]

        def worker():
            subs, sub_err = None, None
            if token:
                try:
                    subs = list_submissions(token)
                except Exception as e:
                    sub_err = str(e)
            items, packs, err = [], [], None
            try:
                packs = fetch_library()
            except Exception as e:
                if "404" not in str(e):  # no packs folder yet = empty library
                    err = str(e)
            for pack in packs:
                try:
                    pages, desc = download_pack(pack, token or None)
                    pack["_pages"], pack["_desc"] = pages, desc
                except Exception as e:
                    log(f"Library: skipped {pack['key']}: {e}")
                    continue
                n = 0
                for pi, pg in enumerate(pages):
                    for bi, b in enumerate(pg["binds"]):
                        if b.get("action") == "page":
                            continue  # only works inside its own set
                        items.append({"key": f"{pack['key']}#{n}", "group": pack["name"], "bind": b,
                                      "pack": pack, "pi": pi, "bi": bi})
                        n += 1
            self.app.ui(self._loaded, packs, items, err, subs, sub_err)

        threading.Thread(target=worker, daemon=True).start()

    def _loaded(self, packs, items, err, subs, sub_err):
        if not self.win.winfo_exists():
            return
        self.packs, self.items, self._err = packs, items, err
        self._subs, self._sub_err = subs, sub_err
        keys = {it["key"] for it in items}
        self.selected &= keys
        self._render()

    # ---- the list ----
    @staticmethod
    def _summary(b):
        if b.get("action") == "reply":
            opts = slash_options(b)
            return (b["label"] or (opts[-1] if opts else "(empty)"),
                    " / ".join([b.get("cmd", "")] + opts))
        detail = " ".join(b["text"].split())
        return b["label"] or detail[:30] or "(empty)", detail

    def _render(self):
        if not self.win.winfo_exists():
            return
        for c in self.list.winfo_children():
            c.destroy()
        if self.app.cfg["panel"]["admin_token"] and (self._subs is not None or self._sub_err):
            self._show_submissions(self._subs, self._sub_err)
            self._section("LIBRARY  -  right-click a tile to edit or delete it")
        if self._err:
            self._message(f"Couldn't load the library.\n\n{self._err}")
        q = self.search.get().strip().lower()
        groups = {}
        for it in self.items:
            title, detail = self._summary(it["bind"])
            if q and q not in f"{title} {detail} {it['group']}".lower():
                continue
            groups.setdefault(it["group"], []).append((it, title, detail))
        if not groups and not self._err:
            self._message("No buttons match your search." if q else "The library is empty right now.")
        for group, rows in groups.items():
            head = tk.Frame(self.list, bg="#eef1f6", pady=4, padx=6)
            head.pack(fill="x", pady=(6, 0))
            tk.Label(head, text=f"{group}  ({len(rows)})", bg="#eef1f6",
                     font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left")
            keys = [it["key"] for it, _, _ in rows]
            all_on = all(k in self.selected for k in keys)
            tog = tk.Label(head, text="Unselect all" if all_on else "Select all", bg="#eef1f6",
                           fg="#2980b9", cursor="hand2", font=("Segoe UI", 8, "underline"))
            tog.pack(side="right")
            if self._admin():
                pk = rows[0][0]["pack"]
                dg = tk.Label(head, text="🗑 Delete group", bg="#eef1f6", fg="#c0392b", cursor="hand2",
                              font=("Segoe UI", 8))
                dg.pack(side="right", padx=(0, 12))
                dg.bind("<Button-1>", lambda e, pk=pk: self.admin_delete_group(pk))
            tog.bind("<Button-1>", lambda e, ks=keys, on=all_on: self._set_many(ks, not on))
            grid = tk.Frame(self.list, bg="#ffffff")
            grid.pack(fill="x", pady=(4, 2))
            for n, (it, title, detail) in enumerate(rows):
                self._tile(grid, it, title, detail, n // self._cols, n % self._cols)
        self._update_count()

    TILE_W, TILE_H = 132, 84

    def _on_resize(self, e):
        self.canvas.itemconfigure(self._win_id, width=e.width)
        cols = max(1, (e.width - 8) // (self.TILE_W + 8))
        if cols != self._cols:
            self._cols = cols
            if self._resize_job:
                self.win.after_cancel(self._resize_job)
            self._resize_job = self.win.after(150, self._render)

    def _tile(self, parent, it, title, detail, r, c):
        """One library button, drawn like a KeyDeck button. Click to select."""
        b, key = it["bind"], it["key"]
        color = b["color"]
        fg = text_color_for(color)
        f = tk.Frame(parent, bg=color, width=self.TILE_W, height=self.TILE_H, cursor="hand2",
                     highlightthickness=3)
        f.grid(row=r, column=c, padx=4, pady=4)
        f.pack_propagate(False)
        name = tk.Label(f, text=title, bg=color, fg=fg, font=("Segoe UI", 9, "bold"),
                        wraplength=self.TILE_W - 14, justify="center", cursor="hand2")
        name.pack(expand=True, fill="both", padx=4, pady=(4, 0))
        small = (b.get("cmd") or "/reply") if b.get("action") == "reply" else ""
        widgets = [f, name]
        if small:
            sl = tk.Label(f, text=small, bg=color, fg=fg, font=("Consolas", 7), cursor="hand2")
            sl.pack(side="bottom", pady=(0, 3))
            widgets.append(sl)
        check = tk.Label(f, text="✓", bg=ACCENT, fg="#111111", font=("Segoe UI", 9, "bold"), padx=3)

        def paint():
            on = key in self.selected
            f.config(highlightbackground=ACCENT if on else "#ffffff",
                     highlightcolor=ACCENT if on else "#ffffff")
            if on:
                check.place(relx=1.0, x=-2, y=2, anchor="ne")
            else:
                check.place_forget()

        def click(e):
            (self.selected.discard if key in self.selected else self.selected.add)(key)
            paint()
            self._update_count()

        def hover_in(e):
            self.hover.config(text=f"{it['group']}  ›  {title}:  {detail}"[:220])

        def menu(e):
            if not self._admin():
                return
            m = tk.Menu(self.win, tearoff=0)
            m.add_command(label="✎ Edit in Library…", command=lambda: self.admin_edit(it))
            m.add_command(label="🗑 Delete from Library", command=lambda: self.admin_delete(it))
            try:
                m.tk_popup(e.x_root, e.y_root)
            finally:
                m.grab_release()

        for wdg in widgets + [check]:
            wdg.bind("<Button-1>", click)
            wdg.bind("<Enter>", hover_in)
            wdg.bind("<Button-3>", menu)
        paint()

    def _set_many(self, keys, on):
        for k in keys:
            (self.selected.add if on else self.selected.discard)(k)
        self._render()

    def clear_selection(self):
        self.selected.clear()
        self._render()

    def _update_count(self):
        n = len(self.selected)
        self.count_label.config(text=f"{n} selected")
        self.add_btn.config(text=f"Add {n}" if n else "Add selected")

    # ---- adding ----
    def add_selected(self):
        chosen = [it["bind"] for it in self.items if it["key"] in self.selected]
        if not chosen:
            messagebox.showinfo(APP_NAME, "Tick at least one button first.", parent=self.win)
            return
        pages = self.app.cfg["pages"]
        k = self.target.current()
        if k < 0 or k >= len(pages):  # new page
            name = simpledialog.askstring(APP_NAME, "Name for the new page:", initialvalue="From Library",
                                          parent=self.win)
            if not name or not name.strip():
                return
            pages.append({"name": unique_name(name.strip()[:30], [pg["name"] for pg in pages]),
                          "id": new_page_id(), "binds": []})
            k = len(pages) - 1
        cleared = self.app.add_buttons_to_page(chosen, k)
        self.app.switch_page(k)
        msg = f'Added {len(chosen)} button(s) to "{pages[k]["name"]}".'
        if cleared:
            msg += f"\n\n{cleared} hotkey(s) were left off because you already use those keys."
        messagebox.showinfo(APP_NAME, msg, parent=self.win)
        self.selected.clear()
        self._fill_targets()
        self.target.current(k)
        self._render()


    # ---- admin: change the live library ----
    def _admin(self):
        return bool(self.app.cfg["panel"]["admin_token"])

    def _admin_write(self, work, done_msg):
        """Run a change against GitHub in the background, then reload the library."""
        token = self.app.cfg["panel"]["admin_token"]

        def worker():
            try:
                work(token)
                err = None
            except Exception as e:
                err = str(e)

            def done():
                if err:
                    hint = ("\n\nSomeone may have changed it at the same time - click Refresh and try again."
                            if "409" in err or "sha" in err.lower() else "")
                    messagebox.showerror(APP_NAME, f"Couldn't change the library.\n\n{err}{hint}",
                                         parent=self.win)
                elif done_msg:
                    messagebox.showinfo(APP_NAME, done_msg, parent=self.win)
                self.load()
            self.app.ui(done)

        threading.Thread(target=worker, daemon=True).start()

    def admin_edit(self, it):
        LibraryItemEditor(self, it)

    def admin_save_item(self, it, new_bind):
        pack = it["pack"]
        pages = json.loads(json.dumps(pack["_pages"]))
        pages[it["pi"]]["binds"][it["bi"]] = clean_bind(new_bind)
        title = new_bind.get("label") or "button"
        self._admin_write(lambda tok: save_pack_file(tok, pack, pages, pack.get("_desc", ""),
                                                     f"Library: edit {title} in {pack['key']}"),
                          f'Saved. "{title}" is updated in everyone\'s Library.')

    def admin_delete(self, it):
        pack = it["pack"]
        title = self._summary(it["bind"])[0]
        if not messagebox.askyesno(APP_NAME, f'Delete "{title}" from everyone\'s Library?\n\n'
                                   "People who already added it keep their copy.", parent=self.win):
            return
        pages = json.loads(json.dumps(pack["_pages"]))
        del pages[it["pi"]]["binds"][it["bi"]]
        pages = [pg for pg in pages if pg["binds"]]
        self.selected.discard(it["key"])
        if pages:
            self._admin_write(lambda tok: save_pack_file(tok, pack, pages, pack.get("_desc", ""),
                                                         f"Library: delete {title} from {pack['key']}"),
                              f'Deleted "{title}".')
        else:  # that was the last button in the file
            self._admin_write(lambda tok: delete_pack_file(tok, pack, f"Library: delete {pack['key']}"),
                              f'Deleted "{title}".')

    def admin_delete_group(self, pack):
        n = sum(len(pg["binds"]) for pg in pack.get("_pages", []))
        if not messagebox.askyesno(APP_NAME, f'Delete the whole group "{pack["name"]}" ({n} buttons) '
                                   "from everyone's Library?\n\nPeople who already added its buttons "
                                   "keep their copies.", parent=self.win):
            return
        self.selected = {k for k in self.selected if not k.startswith(pack["key"] + "#")}
        self._admin_write(lambda tok: delete_pack_file(tok, pack, f"Library: delete {pack['key']}"),
                          f'Deleted "{pack["name"]}".')

    # ---- admin: submissions ----
    def _show_submissions(self, subs, err):
        n = len(subs) if subs else 0
        self._section(f"📥 SUBMISSIONS WAITING FOR YOU ({n})")
        if err:
            tk.Label(self.list, text=f"Couldn't load submissions: {err}", bg="#ffffff", fg="#c0392b",
                     wraplength=480, justify="left").pack(anchor="w")
        elif not subs:
            tk.Label(self.list, text="Nothing waiting.", bg="#ffffff", fg="#777777").pack(anchor="w")
        for sub in subs or []:
            row = tk.Frame(self.list, bg="#fff8ec", pady=6, padx=6)
            row.pack(fill="x", pady=2)
            info = tk.Frame(row, bg="#fff8ec")
            info.pack(side="left", fill="x", expand=True)
            nb = sum(len(pg["binds"]) for pg in sub["pages"])
            tk.Label(info, text=sub["name"], bg="#fff8ec", font=("Segoe UI", 10, "bold"),
                     anchor="w").pack(anchor="w")
            tk.Label(info, text=f"from {sub['submitter']} - {nb} buttons", bg="#fff8ec", fg="#777777",
                     font=("Segoe UI", 8), anchor="w").pack(anchor="w")
            ttk.Button(row, text="Reject", command=lambda sb=sub: self.reject(sb)).pack(side="right", padx=2)
            ttk.Button(row, text="Approve", command=lambda sb=sub: self.approve(sb)).pack(side="right", padx=2)
            ttk.Button(row, text="Preview", command=lambda sb=sub: self._preview_pages(
                sb["name"], sb["pages"], f"From {sb['submitter']}\n{sb['description']}")).pack(side="right", padx=2)
            ttk.Button(row, text="Try it", command=lambda sb=sub: self.try_submission(sb)).pack(side="right", padx=2)

    def _preview_pages(self, title, pages, desc):
        lines = [desc.strip(), ""] if desc and desc.strip() else []
        for pg in pages:
            lines.append(f"Page: {pg['name']}")
            for b in pg["binds"][:30]:
                label = b["label"] or "(no name)"
                what = ("-> go to page" if b.get("action") == "page"
                        else " ".join(b["text"].split())[:70])
                lines.append(f"   • {label}:  {what}")
            if len(pg["binds"]) > 30:
                lines.append(f"   …and {len(pg['binds']) - 30} more")
        messagebox.showinfo(title, "\n".join(lines), parent=self.win)

    def try_submission(self, sub):
        """Add a copy to your own KeyDeck to test it before approving."""
        pages = json.loads(json.dumps(sub["pages"]))
        for pg in pages:
            pg["name"] = f"TEST {pg['name']}"[:30]
        n, _ = self.app.install_pack(pages)
        messagebox.showinfo(APP_NAME, f"Added a test copy ({n} buttons) as a new page so you can try it. "
                            "Delete that page when you're done (right-click its tab).", parent=self.win)

    def approve(self, sub):
        token = self.app.cfg["panel"]["admin_token"]
        filename = safe_pack_filename(sub["name"])
        existing = next((pk for pk in self.packs if pk["key"].lower() == filename.lower()), None)
        msg = f'Publish "{sub["name"]}" from {sub["submitter"]} to everyone\'s Library?'
        if existing:
            msg += (f'\n\nSomething called "{existing["name"]}" is already in the Library. '
                    "It will be REPLACED by this one.")
        if not messagebox.askyesno(APP_NAME, msg, parent=self.win):
            return

        def worker():
            try:
                approve_submission(token, sub, existing["key"] if existing else filename,
                                   existing["sha"] if existing else None)
                err = None
            except Exception as e:
                err = str(e)

            def done():
                if err:
                    messagebox.showerror(APP_NAME, f"Couldn't publish it.\n\n{err}", parent=self.win)
                else:
                    messagebox.showinfo(APP_NAME, f'"{sub["name"]}" is now in everyone\'s Library.',
                                        parent=self.win)
                self.load()
            self.app.ui(done)

        threading.Thread(target=worker, daemon=True).start()

    def reject(self, sub):
        if not messagebox.askyesno(APP_NAME, f'Reject "{sub["name"]}" from {sub["submitter"]}?',
                                   parent=self.win):
            return
        token = self.app.cfg["panel"]["admin_token"]

        def worker():
            try:
                reject_submission(token, sub)
                err = None
            except Exception as e:
                err = str(e)
            self.app.ui(lambda: (messagebox.showerror(APP_NAME, f"Couldn't reject it.\n\n{err}",
                                                      parent=self.win) if err else None, self.load()))

        threading.Thread(target=worker, daemon=True).start()

    def close(self):
        if self.app.library is self:
            self.app.library = None
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
        self._held = {}  # hotkeys currently held down
        self.settings = None
        self.editor = None
        self.library = None
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
                tag, url, notes, is_beta = fetch_latest_release(beta=self.cfg["panel"]["beta"])
                self.ui(self._offer_update, tag, url, notes, manual, is_beta)
            except Exception as e:
                log(f"Update check failed: {e}")
                if manual:
                    self.ui(lambda: messagebox.showwarning(
                        APP_NAME, f"Couldn't check for updates right now.\n\n{e}", parent=self.root))

        threading.Thread(target=worker, daemon=True).start()

    def _offer_update(self, tag, url, notes, manual, is_beta=False):
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
        msg = f"KeyDeck {new}{' (beta - not released to everyone yet)' if is_beta else ''} " \
              f"is available (you have {VERSION})."
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
            if self.cfg["panel"]["no_focus"]:
                # The window can't come to the front by being clicked (that's what
                # keeps the game focused), so raise it ourselves when you click it.
                down = mouse_down_on(self.root)
                if down and not getattr(self, "_was_down", False):
                    raise_quietly(self.root)
                self._was_down = down
            self._poll_n = getattr(self, "_poll_n", 0) + 1
            if self._poll_n % 33 == 0:  # about once a second
                set_no_activate(self.root, self.cfg["panel"]["no_focus"])
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
                # Fires on key-down. (trigger_on_release never fires in the keyboard
                # library without suppress: the released key is already gone from
                # its pressed-keys list when the hotkey is looked up.)
                keyboard.add_hotkey(b["hotkey"], self._on_hotkey, args=(dict(b),), suppress=False)
            except Exception as e:
                self.hotkey_errors.append(f'{b.get("label") or b["hotkey"]}: {e}')
        thk = self.cfg["panel"].get("toggle_hotkey")
        if thk:
            try:
                keyboard.add_hotkey(thk, self._on_toggle_hotkey, suppress=False)
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

    def _once_per_press(self, hk):
        """Holding a hotkey down repeats it; only act once until it's let go."""
        if self._held.get(hk):
            return False
        self._held[hk] = True

        def wait_release():
            end = time.time() + 30
            while time.time() < end:
                try:
                    if not keyboard.is_pressed(hk):
                        break
                except Exception:
                    break
                time.sleep(0.02)
            self._held[hk] = False
        threading.Thread(target=wait_release, daemon=True).start()
        return True

    def _on_toggle_hotkey(self):
        if self._once_per_press(self.cfg["panel"].get("toggle_hotkey") or "toggle"):
            self.ui(self.panel.toggle)

    def _on_hotkey(self, b):
        if not self._once_per_press(b["hotkey"]):
            return
        log(f"Hotkey {b.get('hotkey')} fired")
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
                if b.get("mode") == "copy" and b.get("action") == "text":
                    # just put the text on the clipboard, for {clipboard} buttons to use
                    text = "".join(st[1] for st in plan_text(b["text"]) if st[0] == "text").strip()
                    pyperclip.copy(text)
                    log(f"Copied to clipboard: {text[:40]!r}")
                    continue
                if from_click and not self._restore_target():
                    log("No window to type into yet; click into a text box first.")
                    continue
                self._wait_for_modifiers()
                is_slash = b.get("action") == "reply"
                steps = (slash_plan(b, self.cfg["panel"]["slash_speed"]) if is_slash
                         else plan_text(b["text"]))
                if b.get("enter_before") and not is_slash:  # e.g. open Rust chat first
                    keyboard.send("enter")
                    time.sleep(0.25)
                for step in steps:
                    if step[0] == "text":
                        if is_slash or b.get("mode") == "type":  # slash commands must be typed
                            keyboard.write(step[1], delay=0.003)
                        else:
                            self._paste(step[1])
                    elif step[0] == "key":
                        time.sleep(0.05)
                        try:
                            keyboard.send(step[1])
                        except Exception as e:
                            log(f"Couldn't press key {step[1]!r}: {e}")
                        time.sleep(0.2)  # let the app react (e.g. a console opening)
                    elif step[0] in ("enter", "tab"):
                        time.sleep(0.06)
                        keyboard.send(step[0])
                        time.sleep(0.15)  # give the app a moment before the next part
                    else:
                        time.sleep(step[1])
                if b.get("enter") and not is_slash:  # slash commands already end with Enter
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

    # ---- library submissions -------------------------------------------------
    def submit_page(self, k):
        pg = self.cfg["pages"][k]
        if not pg["binds"]:
            messagebox.showinfo(APP_NAME, "That page has no buttons to submit yet.", parent=self.root)
            return
        if not submit_token():
            messagebox.showinfo(
                APP_NAME, "Submitting isn't switched on in this copy yet.\n\nFor now: right-click the tab > "
                "Export this page..., and send the file to the Library admin.", parent=self.root)
            return
        SubmitDialog(self, pg)

    def submit_button(self, i):
        b = self.cfg["binds"][i]
        if b.get("action") == "page":
            messagebox.showinfo(APP_NAME, "Go-to-page buttons only work with their own pages, so they "
                                "can't be submitted on their own. Submit the whole page instead "
                                "(right-click its tab).", parent=self.root)
            return
        if not submit_token():
            messagebox.showinfo(
                APP_NAME, "Submitting isn't switched on in this copy yet.", parent=self.root)
            return
        name = b.get("label") or " ".join(b.get("text", "").split())[:30] or "Button"
        clean = {k: v for k, v in b.items() if k != "hotkey"}
        clean["hotkey"] = ""  # hotkeys are personal
        SubmitDialog(self, {"name": name[:30], "id": None, "binds": [clean], "_single": True})

    def add_buttons_to_page(self, binds, k):
        """Add copies of library buttons to one of your pages. Returns hotkeys left off."""
        copies = [clean_bind(dict(b)) for b in binds]
        cleared = self._clear_hotkey_clashes([{"binds": copies}])
        if self.editor:
            self.editor.close()
        self.cfg["pages"][k]["binds"].extend(copies)
        self.apply()
        return cleared

    def set_admin_key(self, parent=None, then=None):
        parent = parent or self.root
        cur = self.cfg["panel"]["admin_token"]
        key = simpledialog.askstring(
            APP_NAME, "Paste your Library admin key (leave empty to turn admin off).\n\n"
            "Keep this key private - it stays only on this PC.",
            parent=parent, show="*", initialvalue="")
        if key is None:
            return
        key = key.strip()
        if not key:
            if cur and messagebox.askyesno(APP_NAME, "Turn Library admin off on this PC?", parent=parent):
                self.cfg["panel"]["admin_token"] = ""
                save_config(self.cfg)
            if then:
                then()
            return

        def worker():
            try:
                ok = check_admin_token(key)
                err = None if ok else "That key works, but it doesn't have permission to change the Library."
            except Exception as e:
                ok, err = False, str(e)

            def done():
                if ok:
                    self.cfg["panel"]["admin_token"] = key
                    save_config(self.cfg)
                    messagebox.showinfo(APP_NAME, "Library admin is ON. Open the Library to see submissions.",
                                        parent=parent)
                else:
                    messagebox.showerror(APP_NAME, f"That key didn't work.\n\n{err}", parent=parent)
                if then:
                    then()
            self.ui(done)

        threading.Thread(target=worker, daemon=True).start()

    # ---- button library -----------------------------------------------------
    def open_library(self):
        if self.library and self.library.win.winfo_exists():
            force_foreground(self.library.win)
            return
        self.library = LibraryWindow(self)

    def install_pack(self, new_pages, replace_key=None):
        """Add library pages, or swap in a newer version of pages from the same pack.
        Returns (number of buttons, number of hotkeys left off)."""
        if self.editor:
            self.editor.close()
        pages = self.cfg["pages"]
        cur_page = pages[self.cfg["current_page"]]
        insert_at = len(pages)
        if replace_key:
            old = [k for k, pg in enumerate(pages) if pg.get("pack") == replace_key]
            if old:
                insert_at = old[0]
                # keep "go to page" buttons elsewhere pointing at the updated page
                old_ids = [pages[k]["id"] for k in old]
                for k in reversed(old):
                    del pages[k]
                for pg, oid in zip(new_pages, old_ids):
                    pg["id"] = oid
        remap_page_ids(new_pages, {pg["id"] for pg in pages})
        existing = [pg["name"] for pg in pages]
        for pg in new_pages:
            pg["name"] = unique_name(pg["name"], existing)
            existing.append(pg["name"])
        pages[insert_at:insert_at] = new_pages
        cleared = self._clear_hotkey_clashes(new_pages)
        i = _index_of(pages, cur_page)
        self._set_page(i if i is not None else insert_at)
        self.apply()
        return sum(len(pg["binds"]) for pg in new_pages), cleared

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

    def duplicate_bind(self, i):
        """Copy a button right after itself and open the copy for editing."""
        binds = self.cfg["binds"]
        if i is None or not (0 <= i < len(binds)):
            return
        copy = dict(binds[i])
        copy["hotkey"] = ""  # two buttons can't share a hotkey
        copy["label"] = (copy["label"] + " (copy)")[:40] if copy["label"] else ""
        binds.insert(i + 1, copy)
        self.apply()
        self.edit_bind(i + 1)

    def delete_bind(self, i):
        binds = self.cfg["binds"]
        if not (0 <= i < len(binds)):
            return
        name = binds[i].get("label") or "this button"
        if messagebox.askyesno(APP_NAME, f'Delete "{name}"?', parent=self.root):
            if self.editor:
                self.editor.close()
            del binds[i]
            self.apply()

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
        pg = [{"name": "Mod set", "id": "x1", "binds": [{**DEFAULT_BIND, "label": "hi", "text": "yo {enter}"}]}]
        t, body = make_submission("Mod set", "Tester", "for tickets", pg)
        sub = parse_submission({"title": t, "body": body, "number": 7})
        assert sub["name"] == "Mod set" and sub["submitter"] == "Tester" and sub["description"] == "for tickets"
        assert sub["pages"][0]["binds"][0]["text"] == "yo {enter}"
        assert safe_pack_filename('a/b:c*"d') == "abcd.keydeck"
        sp = slash_plan({"cmd": "/reply", "opt1": "General Support", "opt2": "Raid Not Spawning", "opt3": ""})
        assert sp == [("text", "/reply"), ("wait", 1.0), ("tab",), ("text", "General Support"), ("wait", 1.5),
                      ("tab",), ("text", "Raid Not Spawning"), ("wait", 2.0), ("tab",), ("wait", 0.5), ("enter",)]
        assert plan_text("hi{enter}/tp {clipboard}{Enter}", clip="Bob{enter}") == [
            ("text", "hi"), ("enter",), ("text", "/tp Bob{enter}"), ("enter",)]
        assert plan_text("a{wait 1.5}b") == [("text", "a"), ("wait", 1.5), ("text", "b")]
        assert plan_text("/x(tab)y (enter)") == [("text", "/x"), ("tab",), ("text", "y "), ("enter",)]
        assert plan_text("{key F1}vanish{enter}{key f1}") == [("key", "f1"), ("text", "vanish"), ("enter",),
                                                             ("key", "f1")]
        assert plan_text("{key ctrl+v}") == [("key", "ctrl+v")]
        assert clean_bind({"mode": "copy"})["mode"] == "copy"
        assert clean_bind({})["enter_before"] is False and clean_bind({"enter_before": 1})["enter_before"] is True
        keyboard.parse_hotkey("windows+d")
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
    try:  # open the Library window with sample buttons, select, search, close
        r = tk.Tk()
        r.withdraw()

        class _FakeApp:
            pass
        fa = _FakeApp()
        fa.root, fa.library = r, None
        fa.cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        for pg in fa.cfg["pages"]:
            pg["id"] = new_page_id()
        fa.cfg["binds"] = fa.cfg["pages"][0]["binds"]
        fa.ui = lambda fn, *a: fn(*a)
        real_load = LibraryWindow.load
        LibraryWindow.load = lambda self: None
        try:
            lw = LibraryWindow(fa)
        finally:
            LibraryWindow.load = real_load
        items = [{"key": "s#0", "group": "Set", "bind": clean_bind({"label": "Hi", "text": "hello"})},
                 {"key": "s#1", "group": "Set",
                  "bind": clean_bind({"action": "reply", "opt1": "General Support", "opt2": "Raid"})},
                 {"key": "t#0", "group": "Single", "bind": clean_bind({"text": "gg"})}]
        lw._loaded([], items, None, None, None)
        lw._set_many(["s#0", "s#1"], True)
        assert len(lw.selected) == 2
        lw.search.set("raid")
        lw.search.set("")
        lw.clear_selection()
        assert not lw.selected
        fake_pack = {"key": "Set.keydeck", "name": "Set", "sha": "x", "_pages": [], "_desc": ""}
        for it in items:
            it["pack"], it["pi"], it["bi"] = fake_pack, 0, 0
        fa.cfg["panel"]["admin_token"] = "test"  # draw the admin edit/delete controls too
        lw._render()
        LibraryItemEditor(lw, items[1]).win.destroy()
        LibraryItemEditor(lw, items[0]).win.destroy()
        lw.win.destroy()
        r.destroy()
    except Exception:
        problems.append("library window: " + traceback.format_exc())
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


def focustest():
    """Used by the automatic GitHub build: opens Notepad, clicks a KeyDeck
    button with the real mouse, and checks Notepad never lost focus and got
    the text. Exit code 0 = pass, 1 = fail, 2 = this PC can't run the test."""
    import subprocess
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.FindWindowExW.restype = ctypes.c_void_p
    user32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    app = App()
    app._updating = True  # no update prompts during the test
    errors = []
    app.root.report_callback_exception = lambda *exc: errors.append(
        "".join(traceback.format_exception(*exc))[-600:])
    word = "focustest123"
    pg2 = {"name": "Other", "id": new_page_id(),
           "binds": [clean_bind({"label": "OTHER", "text": "otherpage321", "hotkey": "ctrl+shift+f6"})]}
    pg = {"name": "Test", "id": new_page_id(),
          "binds": [clean_bind({"label": "TEST", "text": word, "mode": "paste"}),
                    clean_bind({"label": "HK", "text": "hotkey456", "hotkey": "ctrl+shift+f9"}),
                    clean_bind({"label": "TYPED", "text": "typed789", "mode": "type", "hotkey": "ctrl+shift+f8"}),
                    clean_bind({"label": "GO", "action": "page", "goto": pg2["id"], "hotkey": "ctrl+shift+f7"})]}
    app.cfg["pages"], app.cfg["current_page"] = [pg, pg2], 0
    app.cfg["binds"] = pg["binds"]
    app.cfg["panel"]["always_on_top"] = True

    procs = []

    def finish(code, msg):
        for pr in procs:  # close Notepad first, or the build waits on it forever
            try:
                pr.kill()
            except Exception:
                pass
        log(f"FOCUSTEST {msg}")
        print(f"FOCUSTEST {msg}", flush=True)
        if _log_file:
            _log_file.flush()
        os._exit(code)

    def on_tk(fn):
        q = queue.Queue()
        app.ui(lambda: q.put(fn()))
        return q.get(timeout=10)

    def bring(hwnd):
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        me = kernel32.GetCurrentThreadId()
        if fg_tid and fg_tid != me:
            user32.AttachThreadInput(fg_tid, me, True)
        user32.ShowWindow(hwnd, 5)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if fg_tid and fg_tid != me:
            user32.AttachThreadInput(fg_tid, me, False)

    def notepad_text(np):
        edit = user32.FindWindowExW(np, None, "Edit", None) or user32.FindWindowExW(np, None, "RichEditD2DPT", None)
        buf = ctypes.create_unicode_buffer(1024)
        user32.SendMessageW(edit, 0x000D, ctypes.c_void_p(1024), ctypes.cast(buf, ctypes.c_void_p))
        return buf.value

    def one_round(np, no_focus):
        def prep():
            app.cfg["panel"]["no_focus"] = no_focus
            app.panel.rebuild()
            app.root.update()
            f = app.panel.grid_frame.winfo_children()[0]
            return f.winfo_rootx() + f.winfo_width() // 2, f.winfo_rooty() + f.winfo_height() // 2
        x, y = on_tk(prep)
        time.sleep(0.5)
        bring(np)
        time.sleep(0.7)
        if user32.GetForegroundWindow() != np:
            return None
        before = notepad_text(np)
        lost = []
        done = threading.Event()

        def watch():
            while not done.is_set():
                fg = user32.GetForegroundWindow()
                if fg != np:
                    lost.append(fg)
                time.sleep(0.005)
        threading.Thread(target=watch, daemon=True).start()
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.2)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up
        time.sleep(2.5)
        done.set()
        after = notepad_text(np)
        return {"lost_focus": bool(lost), "typed": after.count(word) > before.count(word)}

    # (Alt combos can't be faked here: the keyboard library ignores injected
    # keys while Alt is held, so the test uses Ctrl+Shift+F-keys.)
    def press(*vks):  # key presses at the same level as a real keyboard
        # real keyboards send scan codes, and hotkeys are matched on them
        for vk in vks:
            user32.keybd_event(vk, user32.MapVirtualKeyW(vk, 0), 0, 0)
            time.sleep(0.03)
        for vk in reversed(vks):
            user32.keybd_event(vk, user32.MapVirtualKeyW(vk, 0), 2, 0)
            time.sleep(0.03)

    def hotkey_round(np):
        on_tk(lambda: (app._set_page(0), app.apply(), app.register_hotkeys()))
        time.sleep(0.5)
        bring(np)
        time.sleep(0.7)
        if user32.GetForegroundWindow() != np:
            return None
        CTRL, SHIFT = 0x11, 0x10
        res = {}
        seen = []
        keyboard.hook(lambda e: seen.append(f"{e.event_type}:{e.name}"))
        log(f"FOCUSTEST hotkey errors: {app.hotkey_errors}")
        t0 = notepad_text(np)
        press(CTRL, SHIFT, 0x78)  # ctrl+alt+9: paste button
        time.sleep(2.0)
        t1 = notepad_text(np)
        res["paste_hotkey"] = t1.count("hotkey456") == t0.count("hotkey456") + 1  # exactly once
        press(CTRL, SHIFT, 0x77)  # ctrl+alt+8: type-it-out button
        time.sleep(2.5)
        t2 = notepad_text(np)
        res["typed_hotkey"] = t2.count("typed789") > t1.count("typed789")
        press(CTRL, SHIFT, 0x76)  # ctrl+alt+7: go to page "Other"
        time.sleep(1.0)
        res["goto_page_hotkey"] = on_tk(lambda: app.cfg["current_page"]) == 1
        press(CTRL, SHIFT, 0x78)  # page 1's hotkey while page 2 is showing
        time.sleep(2.0)
        t3 = notepad_text(np)
        res["hotkey_from_other_page"] = t3.count("hotkey456") > t2.count("hotkey456")
        press(CTRL, SHIFT, 0x75)  # ctrl+alt+6: button on page 2
        time.sleep(2.0)
        res["page2_hotkey"] = notepad_text(np).count("otherpage321") > t3.count("otherpage321")
        res["kept_focus"] = user32.GetForegroundWindow() == np
        log(f"FOCUSTEST key events seen: {len(seen)} {seen[:12]}")
        return res

    def right_click_round(np):
        def where():
            app._set_page(0)
            app.apply()
            app.root.update()
            f = app.panel.grid_frame.winfo_children()[1]
            t = app.panel.tabs.winfo_children()[0]
            return (f.winfo_rootx() + f.winfo_width() // 2, f.winfo_rooty() + f.winfo_height() // 2,
                    t.winfo_rootx() + 5, t.winfo_rooty() + 5)
        bx, by, tx, ty = on_tk(where)
        out = {}
        for name, x, y in (("button_menu", bx, by), ("tab_menu", tx, ty)):
            n0 = len(errors)
            user32.SetCursorPos(int(x), int(y))
            time.sleep(0.2)
            user32.mouse_event(0x0008, 0, 0, 0, 0)  # right down
            time.sleep(0.05)
            user32.mouse_event(0x0010, 0, 0, 0, 0)  # right up
            time.sleep(1.0)
            press(0x1B)  # Esc closes the menu
            time.sleep(0.8)
            out[name] = len(errors) == n0
        bring(np)
        return out

    def front_round(np):
        """KeyDeck NOT always-on-top, partly behind Notepad: clicking it must
        bring it in front while Notepad keeps focus."""
        def setup():
            app.cfg["panel"]["always_on_top"] = False
            app._set_page(0)
            app.apply()
            app.root.geometry("420x300+100+100")
            app.root.update()
            return get_hwnd(app.root)
        kd = on_tk(setup)
        user32.MoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int]
        user32.MoveWindow(np, 330, 60, 700, 500, True)  # covers KeyDeck's right side
        bring(np)
        time.sleep(0.8)
        probe = _POINT(400, 250)  # a spot where both windows overlap

        def top_at_probe():
            return user32.GetAncestor(user32.WindowFromPoint(probe), 2)
        if top_at_probe() != np or user32.GetForegroundWindow() != np:
            return None
        res = {}
        for name, x, y in (("click_button", 160, 230), ("click_title_bar", 200, 112)):
            bring(np)
            time.sleep(0.6)
            if top_at_probe() != np:
                return None
            user32.SetCursorPos(x, y)
            time.sleep(0.2)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.12)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            time.sleep(1.5)
            res[name + "_came_to_front"] = top_at_probe() == kd
            res[name + "_game_kept_focus"] = user32.GetForegroundWindow() == np
        on_tk(lambda: app.cfg["panel"].update(always_on_top=True))
        return res

    def worker():
        proc = None
        try:
            time.sleep(2.0)
            proc = subprocess.Popen(["notepad.exe"])
            procs.append(proc)
            np = None
            for _ in range(100):
                np = user32.FindWindowW("Notepad", None)
                if np:
                    break
                time.sleep(0.1)
            if not np:
                finish(2, "SKIP: Notepad didn't open")
            time.sleep(1.0)
            old = one_round(np, False)
            new = one_round(np, True)
            if old is None or new is None:
                finish(2, f"SKIP: couldn't put Notepad in front (old={old} new={new})")
            hk = hotkey_round(np)
            rc = right_click_round(np)
            fr = front_round(np)
            msg = f"old way: {old} | no-focus way: {new} | hotkeys: {hk} | right-click: {rc} | to-front: {fr}"
            if errors:
                msg += " | errors: " + " || ".join(errors).replace("\n", " / ")
            if (new["lost_focus"] or not new["typed"] or hk is None or not all(hk.values())
                    or not all(rc.values()) or fr is None or not all(fr.values()) or errors):
                finish(1, "FAIL " + msg)
            finish(0, "OK " + msg)
        except Exception:
            finish(1, "FAIL crashed:\n" + traceback.format_exc())
        finally:
            try:
                proc and proc.kill()
            except Exception:
                pass

    threading.Thread(target=worker, daemon=True).start()
    threading.Timer(60, lambda: finish(2, "SKIP: timed out")).start()
    app.run()


if __name__ == "__main__":
    if "--focustest" in sys.argv:
        focustest()
    if "--selftest" in sys.argv:
        code = selftest()
        if _log_file:
            _log_file.flush()
        os._exit(code)
    main()
