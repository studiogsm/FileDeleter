# -*- coding: utf-8 -*-
"""
Laboratorium Elektroniki — File Deleter v1.6
=============================================
Fixes since v1.5:
  • FIX: access violation in 'Load from clipboard' (missing argtypes/restype
         in ctypes — HDROP handle was truncated to 32-bit on 64-bit Python)
  • FIX: long path support (> MAX_PATH = 260 chars) via \\?\ prefix
  • FIX: 'Pattern' field disappearing after mode switch — pack(before=...)
  • Safer fallback when the clipboard holds a non-file format
"""

import os
import sys
import fnmatch
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
import time
import ctypes
from ctypes import wintypes

VERSION = "v1.6"

# ── Automatic UAC elevation ─────────────────────────────────────────────────
def _require_admin():
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        is_admin = False
    if not is_admin:
        params = " ".join(f'"{a}"' for a in sys.argv)
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1)
        if ret <= 32:
            pass
        else:
            sys.exit(0)

if sys.platform == "win32":
    _require_admin()
# ─────────────────────────────────────────────────────────────────────────────

APP_NAME = f"Laboratorium Elektroniki — File Deleter {VERSION}"

BG      = "#1a1d23"
BG2     = "#22262f"
BG3     = "#2b3040"
ACCENT  = "#e8431a"
ACCENT2 = "#ff6b3d"
FG      = "#e8eaf0"
FG2     = "#9da3b4"
GREEN   = "#3ddc84"
YELLOW  = "#ffd166"
RED     = "#ff4d4d"
BLUE    = "#2563eb"
BORDER  = "#3a3f50"
FONT_MONO = ("Consolas", 9)
FONT_UI   = ("Segoe UI", 9)
FONT_H    = ("Segoe UI Semibold", 10)
FONT_BIG  = ("Segoe UI Semibold", 13)

# Operating modes
MODE_PATTERN = "pattern"
MODE_FOLDER  = "folder"
MODE_LIST    = "list"     # NEW — explicit file list (clipboard/argv/drag-drop)

REG_KEY_NAME    = "FileDeleter"
REG_MENU_LABEL  = "Delete with File Deleter"
SENDTO_LNK_NAME = "FileDeleter.lnk"


# ═════════════════════════════════════════════════════════════════════════════
#  LONG PATH SUPPORT (> MAX_PATH)
# ═════════════════════════════════════════════════════════════════════════════
def _long_path(p):
    r"""
    Returns the path with a \\?\ prefix if it exceeds 240 chars.
    Lets WinAPI bypass the MAX_PATH (260) limit — extends to ~32,000 chars.
    Also handles UNC paths (\\server\share → \\?\UNC\server\share).
    """
    if not p or len(p) < 240:
        return p
    if p.startswith("\\\\?\\"):
        return p
    ap = os.path.abspath(p)
    if ap.startswith("\\\\"):
        return "\\\\?\\UNC\\" + ap[2:]
    return "\\\\?\\" + ap


# ═════════════════════════════════════════════════════════════════════════════
#  READ FILE LIST FROM CLIPBOARD (CF_HDROP)
# ═════════════════════════════════════════════════════════════════════════════
# Type declarations for 64-bit ctypes — CRITICAL. Without them HDROP/HANDLE
# is truncated to 32-bit and calls cause access violations.
_user32  = ctypes.windll.user32
_shell32 = ctypes.windll.shell32

_user32.OpenClipboard.argtypes      = [wintypes.HWND]
_user32.OpenClipboard.restype       = wintypes.BOOL
_user32.CloseClipboard.argtypes     = []
_user32.CloseClipboard.restype      = wintypes.BOOL
_user32.GetClipboardData.argtypes   = [wintypes.UINT]
_user32.GetClipboardData.restype    = wintypes.HANDLE
_user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
_user32.IsClipboardFormatAvailable.restype  = wintypes.BOOL
_shell32.DragQueryFileW.argtypes    = [wintypes.HANDLE, wintypes.UINT,
                                       wintypes.LPWSTR, wintypes.UINT]
_shell32.DragQueryFileW.restype     = wintypes.UINT

CF_HDROP = 15


def read_clipboard_files():
    """
    Reads the file list from the system clipboard (CF_HDROP format).
    Works for ANY number of files — no cmd-line length limit.
    """
    if not _user32.IsClipboardFormatAvailable(CF_HDROP):
        return []
    opened = False
    for _ in range(5):
        if _user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.05)
    if not opened:
        return []
    try:
        h = _user32.GetClipboardData(CF_HDROP)
        if not h:
            return []
        count = _shell32.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
        if not count:
            return []
        files = []
        for i in range(count):
            length = _shell32.DragQueryFileW(h, i, None, 0)
            if length <= 0:
                continue
            buf = ctypes.create_unicode_buffer(length + 1)
            got = _shell32.DragQueryFileW(h, i, buf, length + 1)
            if got > 0:
                files.append(buf.value)
        return files
    finally:
        _user32.CloseClipboard()


# ═════════════════════════════════════════════════════════════════════════════
#  REGISTRY — CONTEXT MENU
# ═════════════════════════════════════════════════════════════════════════════
def _get_launch_target():
    """
    Returns a (target_exe, args_str) tuple for shortcut/registry use.
      .exe (frozen) → (sys.executable, "")
      .py           → (pythonw.exe, '"script.py"')
    """
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable), ""
    py_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(py_dir, "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = sys.executable
    script = os.path.abspath(sys.argv[0])
    return pythonw, f'"{script}"'


def _get_reg_command():
    """Registry command: '"target" [args] "%1"'."""
    target, args = _get_launch_target()
    if args:
        return f'"{target}" {args} "%1"'
    return f'"{target}" "%1"'


def install_context_menu():
    import winreg
    cmd = _get_reg_command()
    target_exe, _ = _get_launch_target()
    bases = [
        r"Directory\shell\\" + REG_KEY_NAME,
        r"*\shell\\" + REG_KEY_NAME,
    ]
    for base in bases:
        with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, base) as k:
            winreg.SetValue(k, "", winreg.REG_SZ, REG_MENU_LABEL)
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, target_exe)
        with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, base + r"\command") as k:
            winreg.SetValue(k, "", winreg.REG_SZ, cmd)


def uninstall_context_menu():
    import winreg
    targets = [
        r"Directory\shell\\" + REG_KEY_NAME + r"\command",
        r"Directory\shell\\" + REG_KEY_NAME,
        r"*\shell\\" + REG_KEY_NAME + r"\command",
        r"*\shell\\" + REG_KEY_NAME,
    ]
    for key_path in targets:
        try:
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_path)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def is_context_menu_installed():
    import winreg
    try:
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                       r"Directory\shell\\" + REG_KEY_NAME).Close()
        return True
    except OSError:
        return False


# ═════════════════════════════════════════════════════════════════════════════
#  SENDTO (Send To menu)
# ═════════════════════════════════════════════════════════════════════════════
def _sendto_path():
    return os.path.join(os.environ.get("APPDATA", ""),
                        "Microsoft", "Windows", "SendTo")


def _sendto_lnk():
    return os.path.join(_sendto_path(), SENDTO_LNK_NAME)


def install_sendto():
    """Creates a .lnk shortcut in the SendTo folder via PowerShell + WScript.Shell."""
    target, args = _get_launch_target()
    lnk = _sendto_lnk()
    workdir = os.path.dirname(target)

    # PowerShell script building .lnk
    ps = (
        "$ErrorActionPreference='Stop';"
        "$WS = New-Object -ComObject WScript.Shell;"
        f"$SC = $WS.CreateShortcut('{lnk}');"
        f"$SC.TargetPath = '{target}';"
        f"$SC.Arguments = '{args}';"
        f"$SC.WorkingDirectory = '{workdir}';"
        f"$SC.IconLocation = '{target},0';"
        "$SC.Description = 'Delete with File Deleter';"
        "$SC.Save();"
    )
    # CREATE_NO_WINDOW = 0x08000000
    res = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", ps],
        creationflags=0x08000000,
        capture_output=True, text=True
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"PowerShell error: {res.stderr or res.stdout}".strip())


def uninstall_sendto():
    lnk = _sendto_lnk()
    if os.path.isfile(lnk):
        os.remove(lnk)


def is_sendto_installed():
    return os.path.isfile(_sendto_lnk())


# ═════════════════════════════════════════════════════════════════════════════
#  APPLICATION
# ═════════════════════════════════════════════════════════════════════════════
class FileDeleterApp(tk.Tk):
    def __init__(self, initial_args=None):
        super().__init__()
        self.title(APP_NAME)
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(900, 720)
        self.geometry("1020x800")

        self._stop_event   = threading.Event()
        self._deleted      = 0
        self._errors       = 0
        self._scanned      = 0
        self._total_size   = 0
        self._phase        = "idle"
        self._found_files  = []
        self._found_dirs   = []
        self._found_size   = 0
        self._t0           = 0.0

        self.mode_var       = tk.StringVar(value=MODE_PATTERN)
        self.keep_root_var  = tk.BooleanVar(value=False)

        self._build_ui()
        self._center()
        self._set_phase("idle")

        self._apply_initial_args(initial_args or [])

    # ── Command-line arguments ───────────────────────────────────────────────
    def _apply_initial_args(self, args):
        # filter out flags
        paths = [a for a in args if not a.startswith("-")]
        if not paths:
            return
        # normalize
        paths = [os.path.abspath(p) for p in paths]

        if len(paths) == 1:
            p = paths[0]
            if os.path.isdir(p):
                self.mode_var.set(MODE_FOLDER)
                self._on_mode_change()
                self.dir_var.set(p.replace("/", "\\"))
                self._log(f"Argument: folder → {p}", "info")
            elif os.path.isfile(p):
                # single file path — LIST mode with one item
                self.mode_var.set(MODE_LIST)
                self._on_mode_change()
                self._load_explicit_list([p])
                self._log(f"Argument: 1 file → {p}", "info")
            else:
                self._log(f"Argument does not exist: {p}", "err")
        else:
            # multiple paths (SendTo, drag-drop)
            self.mode_var.set(MODE_LIST)
            self._on_mode_change()
            self._load_explicit_list(paths)
            self._log(f"Arguments: {len(paths)} paths from command line.",
                      "info")
            # warn about cmd-line limit
            total_len = sum(len(p) for p in paths) + len(paths) * 3
            if total_len > 30000:
                self._log(
                    "WARNING: arguments close to the cmd-line length limit "
                    "(~32,000 chars). Some files may have been truncated. "
                    "For very large selections use the CLIPBOARD "
                    "(Ctrl+C in Explorer → 'Load from clipboard').",
                    "info")

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        tk.Frame(self, bg=ACCENT, height=4).pack(fill="x")

        hdr = tk.Frame(self, bg=BG2, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⬡  FILE DELETER", font=("Segoe UI Semibold", 14),
                 bg=BG2, fg=ACCENT2).pack(side="left", padx=18)
        tk.Label(hdr, text=VERSION, font=FONT_UI,
                 bg=BG2, fg=FG2).pack(side="left")
        tk.Label(hdr, text="Laboratorium Elektroniki", font=FONT_UI,
                 bg=BG2, fg=FG2).pack(side="right", padx=18)

        body = tk.Frame(self, bg=BG, padx=18, pady=12)
        body.pack(fill="both", expand=True)

        # ── Operating mode
        mode_frame = tk.Frame(body, bg=BG)
        mode_frame.pack(fill="x", pady=(0, 8))
        tk.Label(mode_frame, text="Mode:", font=FONT_H,
                 bg=BG, fg=FG).pack(side="left", padx=(0, 12))
        for txt, val in [
            ("  File pattern", MODE_PATTERN),
            ("  Entire folder", MODE_FOLDER),
            ("  List (clipboard / argv)", MODE_LIST),
        ]:
            tk.Radiobutton(mode_frame, text=txt, variable=self.mode_var,
                           value=val, command=self._on_mode_change,
                           font=FONT_UI, bg=BG, fg=FG,
                           selectcolor=BG3, activebackground=BG,
                           activeforeground=ACCENT2, highlightthickness=0,
                           cursor="hand2").pack(side="left", padx=(0, 12))

        # ── Directory (PATTERN and FOLDER modes)
        self.dir_frame = tk.Frame(body, bg=BG)
        self.dir_frame.pack(fill="x")
        self.lbl_dir_caption = tk.Label(self.dir_frame, text="Target directory",
                                         font=FONT_H, bg=BG, fg=FG)
        self.lbl_dir_caption.pack(anchor="w")
        row1 = tk.Frame(self.dir_frame, bg=BG)
        row1.pack(fill="x", pady=(4, 8))
        self.dir_var = tk.StringVar()
        tk.Entry(row1, textvariable=self.dir_var, font=FONT_MONO,
                 bg=BG3, fg=FG, insertbackground=FG2, relief="flat",
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(side="left", fill="x",
                                             expand=True, ipady=6, padx=(0, 8))
        tk.Button(row1, text="Browse…", font=FONT_UI, bg=BG3, fg=FG,
                  activebackground=BG2, activeforeground=ACCENT2,
                  relief="flat", cursor="hand2", padx=12, pady=5,
                  command=self._browse).pack(side="left")

        # ── Pattern
        self.pat_frame = tk.Frame(body, bg=BG)
        self.pat_frame.pack(fill="x", pady=(0, 0))
        tk.Label(self.pat_frame,
                 text="File name pattern  (e.g. LOG.old.* or *.tmp)",
                 font=FONT_H, bg=BG, fg=FG).pack(anchor="w")
        self.pat_var = tk.StringVar(value="LOG.old.*")
        tk.Entry(self.pat_frame, textvariable=self.pat_var, font=FONT_MONO,
                 bg=BG3, fg=ACCENT2, insertbackground=FG2, relief="flat",
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(fill="x", pady=(4, 8), ipady=6)

        # ── List (LIST mode)
        self.list_frame = tk.Frame(body, bg=BG)
        list_top = tk.Frame(self.list_frame, bg=BG)
        list_top.pack(fill="x")
        tk.Label(list_top, text="List of files to delete",
                 font=FONT_H, bg=BG, fg=FG).pack(side="left", anchor="w")
        tk.Button(list_top, text="📋 Load from clipboard  (Ctrl+C)",
                  font=("Segoe UI Semibold", 9), bg=BLUE, fg="white",
                  activebackground="#1d4ed8", activeforeground="white",
                  relief="flat", cursor="hand2", padx=14, pady=4,
                  command=self._load_from_clipboard).pack(side="right",
                                                          padx=(8, 0))
        tk.Button(list_top, text="Clear list", font=FONT_UI,
                  bg=BG3, fg=FG2, activebackground=BG2,
                  activeforeground=FG, relief="flat", cursor="hand2",
                  padx=10, pady=4,
                  command=self._clear_list).pack(side="right")
        self.list_info = tk.Label(self.list_frame,
                                   text="No list. Copy files in Explorer "
                                        "(Ctrl+C) and click "
                                        "'Load from clipboard'.",
                                   font=FONT_UI, bg=BG, fg=FG2,
                                   anchor="w", justify="left")
        self.list_info.pack(fill="x", pady=(4, 8))

        # ── Options (recursion, threads, keep_root)
        opt = tk.Frame(body, bg=BG)
        opt.pack(fill="x", pady=(0, 10))
        # Reference used as anchor — mode panels are packed before it
        self.opt_frame = opt
        self.recurse_var = tk.BooleanVar(value=True)
        self.threads_var = tk.IntVar(value=16)
        self.chk_recurse = tk.Checkbutton(opt,
                                          text="  Subdirectories (recursive)",
                                          variable=self.recurse_var,
                                          font=FONT_UI, bg=BG, fg=FG,
                                          selectcolor=BG3,
                                          activebackground=BG,
                                          activeforeground=ACCENT2,
                                          highlightthickness=0, cursor="hand2")
        self.chk_recurse.pack(side="left", padx=(0, 16))
        self.chk_keep_root = tk.Checkbutton(opt,
                                            text="  Keep the folder itself "
                                                 "(delete contents only)",
                                            variable=self.keep_root_var,
                                            font=FONT_UI, bg=BG, fg=FG,
                                            selectcolor=BG3,
                                            activebackground=BG,
                                            activeforeground=ACCENT2,
                                            highlightthickness=0,
                                            cursor="hand2")
        self.chk_keep_root.pack(side="left", padx=(0, 16))
        tk.Label(opt, text="Threads:", font=FONT_UI,
                 bg=BG, fg=FG2).pack(side="left")
        self.threads_spin = tk.Spinbox(opt, from_=1, to=64,
                                        textvariable=self.threads_var,
                                        width=4, font=FONT_UI, bg=BG3, fg=FG,
                                        buttonbackground=BG3, relief="flat",
                                        highlightthickness=1,
                                        highlightbackground=BORDER)
        self.threads_spin.pack(side="left", padx=(4, 8))

        # ── Stats
        stats = tk.Frame(body, bg=BG3, pady=6, padx=12,
                         highlightthickness=1, highlightbackground=BORDER)
        stats.pack(fill="x", pady=(0, 8))
        self.lbl_scanned  = self._stat_cell(stats, "Scanned", "—")
        self._vsep(stats)
        self.lbl_found    = self._stat_cell(stats, "Found", "—")
        self._vsep(stats)
        self.lbl_found_sz = self._stat_cell(stats, "To delete", "—")
        self._vsep(stats)
        self.lbl_deleted  = self._stat_cell(stats, "Deleted", "—")
        self._vsep(stats)
        self.lbl_freed    = self._stat_cell(stats, "Freed", "—")
        self._vsep(stats)
        self.lbl_errors   = self._stat_cell(stats, "Errors", "—")
        self._vsep(stats)
        self.lbl_speed    = self._stat_cell(stats, "Files/s", "—")

        # ── Progress
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Del.Horizontal.TProgressbar",
                        troughcolor=BG3, background=ACCENT,
                        bordercolor=BG3, lightcolor=ACCENT2, darkcolor=ACCENT)
        self.progress = ttk.Progressbar(body, style="Del.Horizontal.TProgressbar",
                                         mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 6))

        # ── Action button bar (bottom)
        br = tk.Frame(body, bg=BG)
        br.pack(fill="x", side="bottom", pady=(8, 0))

        # ── Integration bar (context menu + SendTo)
        integ = tk.Frame(body, bg=BG)
        integ.pack(fill="x", side="bottom", pady=(6, 0))

        # Row 1: context menu
        r_ctx = tk.Frame(integ, bg=BG)
        r_ctx.pack(fill="x")
        tk.Label(r_ctx, text="Context menu (right-click):",
                 font=FONT_UI, bg=BG, fg=FG2, width=34,
                 anchor="w").pack(side="left")
        self.btn_install_ctx = tk.Button(r_ctx, text="➕ Add",
                                          font=FONT_UI, bg=BG3, fg=FG,
                                          activebackground=BG2,
                                          activeforeground=GREEN,
                                          relief="flat", cursor="hand2",
                                          padx=10, pady=4,
                                          command=self._install_menu)
        self.btn_install_ctx.pack(side="left", padx=(0, 4))
        self.btn_uninstall_ctx = tk.Button(r_ctx, text="➖ Remove",
                                            font=FONT_UI, bg=BG3, fg=FG,
                                            activebackground=BG2,
                                            activeforeground=RED,
                                            relief="flat", cursor="hand2",
                                            padx=10, pady=4,
                                            command=self._uninstall_menu)
        self.btn_uninstall_ctx.pack(side="left", padx=(0, 4))
        self.lbl_ctx_status = tk.Label(r_ctx, text="", font=FONT_UI,
                                        bg=BG, fg=FG2)
        self.lbl_ctx_status.pack(side="left", padx=(8, 0))

        # Row 2: SendTo
        r_st = tk.Frame(integ, bg=BG)
        r_st.pack(fill="x", pady=(3, 0))
        tk.Label(r_st, text="'Send To' menu:",
                 font=FONT_UI, bg=BG, fg=FG2, width=34,
                 anchor="w").pack(side="left")
        self.btn_install_st = tk.Button(r_st, text="➕ Add",
                                         font=FONT_UI, bg=BG3, fg=FG,
                                         activebackground=BG2,
                                         activeforeground=GREEN,
                                         relief="flat", cursor="hand2",
                                         padx=10, pady=4,
                                         command=self._install_sendto)
        self.btn_install_st.pack(side="left", padx=(0, 4))
        self.btn_uninstall_st = tk.Button(r_st, text="➖ Remove",
                                           font=FONT_UI, bg=BG3, fg=FG,
                                           activebackground=BG2,
                                           activeforeground=RED,
                                           relief="flat", cursor="hand2",
                                           padx=10, pady=4,
                                           command=self._uninstall_sendto)
        self.btn_uninstall_st.pack(side="left", padx=(0, 4))
        self.lbl_st_status = tk.Label(r_st, text="", font=FONT_UI,
                                       bg=BG, fg=FG2)
        self.lbl_st_status.pack(side="left", padx=(8, 0))

        self._refresh_integ_status()

        # ── Log
        tk.Label(body, text="Operation log", font=FONT_H,
                 bg=BG, fg=FG2).pack(anchor="w")
        lf = tk.Frame(body, bg=BG3, highlightthickness=1,
                      highlightbackground=BORDER)
        lf.pack(fill="both", expand=True, pady=(4, 0))
        self.log = tk.Text(lf, font=FONT_MONO, bg=BG3, fg=FG2,
                           insertbackground=FG, relief="flat",
                           wrap="none", state="disabled",
                           selectbackground=BG, selectforeground=ACCENT2)
        sbv = tk.Scrollbar(lf, orient="vertical",
                           command=self.log.yview, bg=BG3)
        sbh = tk.Scrollbar(lf, orient="horizontal",
                           command=self.log.xview, bg=BG3)
        self.log.configure(yscrollcommand=sbv.set, xscrollcommand=sbh.set)
        self.log.tag_config("ok",   foreground=GREEN)
        self.log.tag_config("err",  foreground=RED)
        self.log.tag_config("info", foreground=YELLOW)
        self.log.tag_config("hdr",  foreground=ACCENT2)
        sbv.pack(side="right", fill="y")
        sbh.pack(side="bottom", fill="x")
        self.log.pack(fill="both", expand=True)

        # ── Action buttons
        self.btn_scan = tk.Button(br, text="🔍  SCAN",
                                   font=("Segoe UI Semibold", 10),
                                   bg=BLUE, fg="white",
                                   activebackground="#1d4ed8",
                                   activeforeground="white",
                                   relief="flat", cursor="hand2",
                                   padx=22, pady=7,
                                   command=self._start_scan)
        self.btn_scan.pack(side="left", padx=(0, 8))

        self.btn_delete = tk.Button(br, text="🗑  DELETE ALL",
                                     font=("Segoe UI Semibold", 10),
                                     bg=ACCENT, fg="white",
                                     activebackground=ACCENT2,
                                     activeforeground="white",
                                     relief="flat", cursor="hand2",
                                     padx=22, pady=7,
                                     command=self._start_delete)
        self.btn_delete.pack(side="left", padx=(0, 8))

        self.btn_stop = tk.Button(br, text="■  STOP",
                                   font=("Segoe UI Semibold", 10),
                                   bg=BG3, fg=FG2,
                                   activebackground=RED,
                                   activeforeground="white",
                                   relief="flat", cursor="hand2",
                                   padx=22, pady=7,
                                   state="disabled",
                                   command=self._stop)
        self.btn_stop.pack(side="left", padx=(0, 8))

        tk.Button(br, text="Clear log", font=FONT_UI, bg=BG3, fg=FG2,
                  activebackground=BG2, activeforeground=FG,
                  relief="flat", cursor="hand2", padx=12, pady=7,
                  command=self._clear_log).pack(side="left")

        self.lbl_status = tk.Label(br, text="Ready.", font=FONT_UI,
                                    bg=BG, fg=FG2)
        self.lbl_status.pack(side="right", padx=4)

        self._on_mode_change()

    # ── Helpers ──────────────────────────────────────────────────────────────
    def _stat_cell(self, p, lbl, val):
        f = tk.Frame(p, bg=BG3)
        f.pack(side="left", expand=True)
        tk.Label(f, text=lbl, font=("Segoe UI", 8), bg=BG3, fg=FG2).pack()
        w = tk.Label(f, text=val, font=FONT_BIG, bg=BG3, fg=FG)
        w.pack()
        return w

    def _vsep(self, p):
        tk.Frame(p, bg=BORDER, width=1).pack(side="left", fill="y",
                                              padx=6, pady=4)

    def _center(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _log(self, msg, tag=""):
        def _do():
            self.log.configure(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log.insert("end", f"[{ts}] {msg}\n", tag)
            self.log.see("end")
            self.log.configure(state="disabled")
        self.after(0, _do)

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    @staticmethod
    def _fmt(n):
        for u in ("B","KB","MB","GB","TB"):
            if n < 1024: return f"{n:.1f} {u}"
            n /= 1024
        return f"{n:.1f} PB"

    # ── Mode switching ────────────────────────────────────────────────────────
    def _on_mode_change(self):
        mode = self.mode_var.get()

        self.dir_frame.pack_forget()
        self.pat_frame.pack_forget()
        self.list_frame.pack_forget()

        # before=opt_frame ensures mode panels ALWAYS land in the same
        # place (above the options bar) no matter how many times the user
        # switches mode. Fixes the disappearing 'Pattern' field.
        anchor = self.opt_frame

        if mode == MODE_PATTERN:
            self.dir_frame.pack(fill="x", before=anchor)
            self.lbl_dir_caption.config(text="Target directory")
            self.pat_frame.pack(fill="x", pady=(0, 0), before=anchor)
            self.chk_recurse.config(state="normal")
            self.chk_keep_root.config(state="disabled")
        elif mode == MODE_FOLDER:
            self.dir_frame.pack(fill="x", before=anchor)
            self.lbl_dir_caption.config(
                text="Folder to DELETE  (with all contents!)")
            self.chk_recurse.config(state="disabled")
            self.recurse_var.set(True)
            self.chk_keep_root.config(state="normal")
        else:  # MODE_LIST
            self.list_frame.pack(fill="x", before=anchor)
            self.chk_recurse.config(state="disabled")
            self.chk_keep_root.config(state="disabled")

        # Repack integ and log in the proper order
        # (left as-is — they are packed side="bottom" + log expand)

        # reset
        self._found_files = []
        self._found_dirs  = []
        self._found_size  = 0
        self._set_phase("idle")

    # ── List: clipboard / argv ────────────────────────────────────────────────
    def _load_from_clipboard(self):
        try:
            files = read_clipboard_files()
        except Exception as ex:
            messagebox.showerror("Clipboard error",
                                  f"Failed to read clipboard:\n{ex}")
            return
        if not files:
            messagebox.showwarning(
                "Clipboard empty",
                "No files in the clipboard.\n\n"
                "In Windows Explorer, select files and press Ctrl+C.")
            return
        self.mode_var.set(MODE_LIST)
        self._on_mode_change()
        self._load_explicit_list(files)
        self._log(f"Loaded from clipboard: {len(files):,} items.".replace(",", " "), "ok")

    def _load_explicit_list(self, paths):
        """Loads a list of paths into _found_files (with sizes)."""
        self._found_files = []
        self._found_dirs  = []
        self._found_size  = 0
        skipped = 0
        for p in paths:
            lp = _long_path(p)
            try:
                is_file = os.path.isfile(lp)
                is_dir  = os.path.isdir(lp)
            except OSError:
                is_file = is_dir = False
            if is_file:
                try:
                    sz = os.path.getsize(lp)
                except OSError:
                    sz = 0
                self._found_files.append((p, sz))
                self._found_size += sz
            elif is_dir:
                self._found_dirs.append((p, 0))
            else:
                skipped += 1
        n = len(self._found_files)
        nd = len(self._found_dirs)
        info_lines = [
            f"Files: {n:,}".replace(",", " "),
            f"Folders: {nd:,}".replace(",", " "),
            f"Total file size: {self._fmt(self._found_size)}",
        ]
        if skipped:
            info_lines.append(f"Skipped (not found): {skipped}")
        self.list_info.config(text="   •   ".join(info_lines), fg=FG)

        # od razu w fazie 'ready'
        self.lbl_scanned.config(text="—", fg=FG)
        self.lbl_found.config(
            text=(f"{n:,} + {nd:,}".replace(",", " ") if nd
                  else f"{n:,}".replace(",", " ")),
            fg=GREEN if (n or nd) else FG2)
        self.lbl_found_sz.config(text=self._fmt(self._found_size))
        for w in (self.lbl_deleted, self.lbl_freed, self.lbl_errors,
                  self.lbl_speed):
            w.config(text="—", fg=FG)
        if n or nd:
            self._set_phase("ready")
            self.lbl_status.config(
                text=f"Ready: {n:,} files ({self._fmt(self._found_size)})"
                     .replace(",", " "), fg=YELLOW)
        else:
            self._set_phase("idle")
            self.lbl_status.config(text="No items.", fg=FG2)

    def _clear_list(self):
        self._found_files = []
        self._found_dirs  = []
        self._found_size  = 0
        self.list_info.config(text="No list. Copy files in Explorer "
                                    "(Ctrl+C) and click "
                                    "'Load from clipboard'.", fg=FG2)
        for w in (self.lbl_scanned, self.lbl_found, self.lbl_found_sz,
                  self.lbl_deleted, self.lbl_freed, self.lbl_errors,
                  self.lbl_speed):
            w.config(text="—", fg=FG)
        self._set_phase("idle")
        self.lbl_status.config(text="List cleared.", fg=FG2)

    # ── Log file writing ──────────────────────────────────────────────────────
    def _get_log_dir(self):
        base = os.path.dirname(os.path.abspath(sys.argv[0]))
        log_dir = os.path.join(base, "FileDeleter_Logs")
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            log_dir = os.path.join(os.path.expanduser("~"),
                                    "FileDeleter_Logs")
            os.makedirs(log_dir, exist_ok=True)
        return log_dir

    def _save_log(self, session_type: str, summary: dict):
        ts    = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        fname = f"log_{session_type}_{ts}.txt"
        fpath = os.path.join(self._get_log_dir(), fname)
        lines = []
        lines.append("=" * 70)
        lines.append(f"  Laboratorium Elektroniki — File Deleter {VERSION}")
        lines.append(f"  Session: {session_type.upper()}   "
                     f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 70)
        for k, v in summary.items():
            lines.append(f"  {k:<28} {v}")
        lines.append("-" * 70)
        lines.append("  DETAILS (from log window):")
        lines.append("-" * 70)
        self.log.configure(state="normal")
        log_content = self.log.get("1.0", "end").strip()
        self.log.configure(state="disabled")
        lines.append(log_content)
        lines.append("=" * 70)
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self._log(f"Log saved: {fpath}", "ok")
        except Exception as ex:
            self._log(f"Cannot save log: {ex}", "err")

    # ── State machine ─────────────────────────────────────────────────────────
    def _set_phase(self, phase):
        self._phase = phase
        # SCAN only makes sense in PATTERN and FOLDER modes
        mode = self.mode_var.get()
        scan_applicable = mode in (MODE_PATTERN, MODE_FOLDER)
        if phase == "idle":
            self.btn_scan.config(state="normal" if scan_applicable else "disabled")
            self.btn_delete.config(state="disabled")
            self.btn_stop.config(state="disabled")
        elif phase == "scanning":
            self.btn_scan.config(state="disabled")
            self.btn_delete.config(state="disabled")
            self.btn_stop.config(state="normal")
        elif phase == "ready":
            self.btn_scan.config(state="normal" if scan_applicable else "disabled")
            self.btn_delete.config(state="normal")
            self.btn_stop.config(state="disabled")
        elif phase == "deleting":
            self.btn_scan.config(state="disabled")
            self.btn_delete.config(state="disabled")
            self.btn_stop.config(state="normal")
        elif phase == "done":
            self.btn_scan.config(state="normal" if scan_applicable else "disabled")
            self.btn_delete.config(state="disabled")
            self.btn_stop.config(state="disabled")

    # ── Browse ────────────────────────────────────────────────────────────────
    def _browse(self):
        d = filedialog.askdirectory(title="Select directory")
        if d:
            self.dir_var.set(d.replace("/", "\\"))
            self._set_phase("idle")
            self._found_files = []
            self._found_dirs  = []

    # ── Stop ──────────────────────────────────────────────────────────────────
    def _stop(self):
        self._stop_event.set()
        self.lbl_status.config(text="Stopping…", fg=YELLOW)

    # ── Integrations (context menu + SendTo) ──────────────────────────────────
    def _refresh_integ_status(self):
        try:
            ok = is_context_menu_installed()
            self.lbl_ctx_status.config(
                text="✓ installed" if ok else "✗ not installed",
                fg=GREEN if ok else FG2)
        except Exception:
            self.lbl_ctx_status.config(text="", fg=FG2)
        try:
            ok = is_sendto_installed()
            self.lbl_st_status.config(
                text="✓ installed" if ok else "✗ not installed",
                fg=GREEN if ok else FG2)
        except Exception:
            self.lbl_st_status.config(text="", fg=FG2)

    def _install_menu(self):
        try:
            install_context_menu()
            self._log("Context menu: entry added "
                      "(folder + file).", "ok")
            self._refresh_integ_status()
            messagebox.showinfo(
                "Context menu",
                "Entry added.\n\n"
                "Right-click a FOLDER (not on selected files!) "
                "→ '" + REG_MENU_LABEL + "'.\n\n"
                "NOTE: Windows hides custom menu entries when more "
                "than ~15 files are selected — that's a system "
                "limit. For large selections use 'Send To' or the "
                "clipboard (Ctrl+C → 'Load from clipboard').")
        except PermissionError:
            messagebox.showerror("Error", "No permission. "
                                          "Uruchom jako administrator.")
        except Exception as ex:
            self._log(f"Menu install error: {ex}", "err")
            messagebox.showerror("Error", str(ex))

    def _uninstall_menu(self):
        try:
            uninstall_context_menu()
            self._log("Context menu: entry removed.", "ok")
            self._refresh_integ_status()
            messagebox.showinfo("Context menu", "Entry removed.")
        except Exception as ex:
            self._log(f"Menu uninstall error: {ex}", "err")
            messagebox.showerror("Error", str(ex))

    def _install_sendto(self):
        try:
            install_sendto()
            self._log("'Send To': shortcut added.", "ok")
            self._refresh_integ_status()
            messagebox.showinfo(
                "Send To",
                "Shortcut added.\n\n"
                "In Explorer: select files/folders → right-click → "
                "'Send To' → 'FileDeleter'.\n\n"
                "Limit: ~200 files (Windows cmd-line length limit "
                "~32,000 chars). For larger selections use the "
                "clipboard (Ctrl+C → 'Load from clipboard' in the GUI).")
        except Exception as ex:
            self._log(f"'Send To' install error: {ex}", "err")
            messagebox.showerror("Error", str(ex))

    def _uninstall_sendto(self):
        try:
            uninstall_sendto()
            self._log("'Send To': shortcut removed.", "ok")
            self._refresh_integ_status()
            messagebox.showinfo("Send To", "Shortcut removed.")
        except Exception as ex:
            self._log(f"'Send To' uninstall error: {ex}", "err")
            messagebox.showerror("Error", str(ex))

    # ═════════════════════════════════════════════════════════════════════════
    #  PHASE 1 — SCANNING (PATTERN and FOLDER only)
    # ═════════════════════════════════════════════════════════════════════════
    def _start_scan(self):
        mode = self.mode_var.get()
        if mode == MODE_LIST:
            messagebox.showinfo("List mode",
                                 "In list mode scanning is not "
                                 "needed — press 'DELETE ALL' "
                                 "directly.")
            return

        directory = self.dir_var.get().strip()
        if not directory or not os.path.isdir(directory):
            messagebox.showerror("Error", "Enter a valid directory.")
            return
        if mode == MODE_PATTERN:
            pattern = self.pat_var.get().strip()
            if not pattern:
                messagebox.showwarning("No pattern",
                                        "Enter a file name pattern.")
                return

        self._found_files = []
        self._found_dirs  = []
        self._found_size  = 0
        self._scanned     = 0
        self._stop_event.clear()
        self._t0 = time.time()
        self._set_phase("scanning")
        self.progress.start(10)
        self.lbl_status.config(text="Scanning…", fg=YELLOW)
        self.lbl_found.config(text="…", fg=YELLOW)
        for w in (self.lbl_deleted, self.lbl_freed, self.lbl_errors,
                  self.lbl_speed):
            w.config(text="—", fg=FG)

        if mode == MODE_PATTERN:
            self._log(f"══ SCAN [PATTERN]  "
                      f"directory: {directory}  "
                      f"pattern: {self.pat_var.get()}", "hdr")
            threading.Thread(
                target=self._run_scan_pattern,
                args=(directory, self.pat_var.get(),
                      self.recurse_var.get()),
                daemon=True).start()
        else:
            self._log(f"══ SCAN [FOLDER]  "
                      f"folder: {directory}", "hdr")
            threading.Thread(
                target=self._run_scan_folder,
                args=(directory,),
                daemon=True).start()

        self.after(300, self._tick_scan)

    def _run_scan_pattern(self, directory, pattern, recurse):
        try:
            walker = os.walk(directory) if recurse else \
                     [(directory, [], os.listdir(directory))]
            pat_lo = pattern.lower()
            for root, dirs, files in walker:
                if self._stop_event.is_set():
                    break
                for fname in files:
                    self._scanned += 1
                    if fnmatch.fnmatch(fname.lower(), pat_lo):
                        fpath = os.path.join(root, fname)
                        try:
                            sz = os.path.getsize(fpath)
                        except OSError:
                            sz = 0
                        self._found_files.append((fpath, sz))
                        self._found_size += sz
        except Exception as ex:
            self._log(f"SCAN ERROR: {ex}", "err")
        finally:
            self.after(0, self._finish_scan)

    def _run_scan_folder(self, directory):
        try:
            base_depth = directory.rstrip("\\/").count(os.sep)
            for root, dirs, files in os.walk(directory):
                if self._stop_event.is_set():
                    break
                depth = root.count(os.sep) - base_depth
                self._found_dirs.append((root, depth))
                for fname in files:
                    self._scanned += 1
                    fpath = os.path.join(root, fname)
                    try:
                        sz = os.path.getsize(fpath)
                    except OSError:
                        sz = 0
                    self._found_files.append((fpath, sz))
                    self._found_size += sz
        except Exception as ex:
            self._log(f"SCAN ERROR: {ex}", "err")
        finally:
            self.after(0, self._finish_scan)

    def _tick_scan(self):
        if self._phase == "scanning":
            self.lbl_scanned.config(
                text=f"{self._scanned:,}".replace(",", " "))
            self.lbl_found.config(
                text=f"{len(self._found_files):,}".replace(",", " "),
                fg=YELLOW)
            self.lbl_found_sz.config(text=self._fmt(self._found_size))
            self.after(300, self._tick_scan)

    def _finish_scan(self):
        self.progress.stop()
        elapsed = time.time() - self._t0
        n_files = len(self._found_files)
        n_dirs  = len(self._found_dirs)
        sz = self._found_size
        mode = self.mode_var.get()

        self.lbl_scanned.config(
            text=f"{self._scanned:,}".replace(",", " "), fg=FG)
        if mode == MODE_FOLDER:
            self.lbl_found.config(
                text=f"{n_files:,} + {n_dirs:,}".replace(",", " "),
                fg=GREEN if (n_files or n_dirs) else FG2)
        else:
            self.lbl_found.config(
                text=f"{n_files:,}".replace(",", " "),
                fg=GREEN if n_files else FG2)
        self.lbl_found_sz.config(text=self._fmt(sz))

        if self._stop_event.is_set():
            self._log("Scan interrupted.", "info")
            self._set_phase("idle")
            self.lbl_status.config(text="Interrupted.", fg=YELLOW)
            return

        if mode == MODE_FOLDER:
            self._log(f"Scan OK: {n_files:,} files, "
                      f"{n_dirs:,} folders ({self._fmt(sz)}), "
                      f"{elapsed:.1f}s", "ok")
        else:
            self._log(f"Scan OK: {self._scanned:,} examined, "
                      f"{n_files:,} matches ({self._fmt(sz)}), "
                      f"{elapsed:.1f}s", "ok")

        if n_files == 0 and n_dirs == 0:
            self._log("Nothing to delete.", "info")
            self._set_phase("idle")
            self.lbl_status.config(text="No matches.", fg=FG2)
            return

        self._set_phase("ready")
        self.lbl_status.config(
            text=f"Ready: {n_files:,} files ({self._fmt(sz)}).",
            fg=YELLOW)

        self._save_log("skanowanie", {
            "Mode":                 mode,
            "Directory":            self.dir_var.get(),
            "Pattern":              (self.pat_var.get() if mode == MODE_PATTERN
                                      else "(N/A)"),
            "Files scanned":        f"{self._scanned:,}",
            "Files found":          f"{n_files:,}",
            "Folders found":        (f"{n_dirs:,}" if mode == MODE_FOLDER
                                      else "(N/A)"),
            "Total size":           self._fmt(sz),
            "Scan time":            f"{elapsed:.1f} s",
        })

    # ═════════════════════════════════════════════════════════════════════════
    #  PHASE 2 — DELETION
    # ═════════════════════════════════════════════════════════════════════════
    def _start_delete(self):
        n_files = len(self._found_files)
        n_dirs  = len(self._found_dirs)
        if n_files == 0 and n_dirs == 0:
            messagebox.showinfo("No data",
                                 "First run a scan or load a list.")
            return

        mode = self.mode_var.get()
        sz   = self._fmt(self._found_size)

        if mode == MODE_FOLDER:
            keep = self.keep_root_var.get()
            msg = (f"Delete folder contents?\n\n  {self.dir_var.get()}\n\n"
                   f"Files: {n_files:,}, subfolders: {n_dirs:,} ({sz})\n"
                   f"Mode: " +
                   ("KEEP the folder (delete contents only)"
                    if keep else "DELETE folder with all contents") +
                   "\n\nIRREVERSIBLE OPERATION!")
        elif mode == MODE_LIST:
            msg = (f"Delete {n_files:,} files ({sz})"
                   + (f" and {n_dirs:,} folders" if n_dirs else "")
                   + "?\n\nIrreversible operation.")
        else:
            msg = (f"Delete {n_files:,} files ({sz})?\n\n"
                   "Irreversible operation.")

        if not messagebox.askyesno("Confirm", msg):
            return

        self._deleted    = 0
        self._errors     = 0
        self._total_size = 0
        self._stop_event.clear()
        self._t0 = time.time()
        self._set_phase("deleting")
        self.progress.start(10)
        self.lbl_status.config(text="Deleting…", fg=ACCENT2)
        threads = max(1, min(self.threads_var.get(), 64))

        if mode == MODE_FOLDER:
            self._log(f"══ DELETE [FOLDER]  {n_files:,} files + "
                      f"{n_dirs:,} folders  threads: {threads}", "hdr")
            threading.Thread(
                target=self._run_delete_folder,
                args=(list(self._found_files),
                      list(self._found_dirs), threads,
                      self.keep_root_var.get(), self.dir_var.get()),
                daemon=True).start()
        elif mode == MODE_LIST:
            self._log(f"══ DELETE [LIST]  {n_files:,} files + "
                      f"{n_dirs:,} folders  threads: {threads}", "hdr")
            threading.Thread(
                target=self._run_delete_list,
                args=(list(self._found_files),
                      list(self._found_dirs), threads),
                daemon=True).start()
        else:
            self._log(f"══ DELETE [PATTERN]  {n_files:,} files  "
                      f"threads: {threads}", "hdr")
            threading.Thread(
                target=self._run_delete_pattern,
                args=(list(self._found_files), threads),
                daemon=True).start()

        self.after(300, self._tick_delete)

    def _delete_one_file(self, item):
        path, size = item
        if self._stop_event.is_set():
            return False, 0, ""
        lp = _long_path(path)
        try:
            os.remove(lp)
            return True, size, ""
        except PermissionError:
            try:
                os.chmod(lp, 0o666)
                os.remove(lp)
                return True, size, ""
            except Exception as ex:
                return False, 0, f"{path} → {ex}"
        except Exception as ex:
            return False, 0, f"{path} → {ex}"

    def _run_delete_pattern(self, files, threads):
        try:
            with ThreadPoolExecutor(max_workers=threads) as ex:
                futures = {ex.submit(self._delete_one_file, f): f
                           for f in files}
                done = 0
                for fut in as_completed(futures):
                    ok, size, errmsg = fut.result()
                    done += 1
                    if ok:
                        self._deleted    += 1
                        self._total_size += size
                    else:
                        if errmsg:
                            self._errors += 1
                            if self._errors < 50:
                                self._log(f"ERROR: {errmsg}", "err")
                    if done % 1000 == 0:
                        self._log(
                            f"  … {self._deleted:,} deleted  "
                            f"{self._fmt(self._total_size)}", "info")
        except Exception as ex:
            self._log(f"CRITICAL ERROR: {ex}", "err")
        finally:
            self.after(0, self._finish_delete)

    def _run_delete_folder(self, files, dirs, threads, keep_root, root_path):
        # STEP 1: files in parallel
        try:
            self._log(f"  Step 1/2: deleting {len(files):,} files…",
                      "info")
            with ThreadPoolExecutor(max_workers=threads) as ex:
                futures = {ex.submit(self._delete_one_file, f): f
                           for f in files}
                done = 0
                for fut in as_completed(futures):
                    ok, size, errmsg = fut.result()
                    done += 1
                    if ok:
                        self._deleted    += 1
                        self._total_size += size
                    else:
                        if errmsg:
                            self._errors += 1
                            if self._errors < 50:
                                self._log(f"ERROR: {errmsg}", "err")
                            elif self._errors == 50:
                                self._log("(further errors counted "
                                          "without logging)", "info")
                    if done % 2000 == 0:
                        self._log(
                            f"  … {self._deleted:,} files  "
                            f"{self._fmt(self._total_size)}", "info")
        except Exception as ex:
            self._log(f"CRITICAL ERROR (files): {ex}", "err")

        if self._stop_event.is_set():
            self.after(0, self._finish_delete)
            return

        # STEP 2: directories deepest-first
        try:
            self._log(f"  Step 2/2: deleting {len(dirs):,} directories…",
                      "info")
            # optionally skip the root
            root_abs = os.path.abspath(root_path).rstrip("\\/")
            dirs_sorted = sorted(dirs, key=lambda x: -x[1])
            removed = 0
            for dpath, _depth in dirs_sorted:
                if self._stop_event.is_set():
                    break
                if keep_root and os.path.abspath(dpath).rstrip("\\/") == root_abs:
                    continue
                lpath = _long_path(dpath)
                try:
                    os.rmdir(lpath)
                    removed += 1
                except OSError as ex:
                    try:
                        shutil.rmtree(lpath, ignore_errors=True)
                        if not os.path.exists(lpath):
                            removed += 1
                        else:
                            self._errors += 1
                            self._log(f"ERROR (dir): {dpath} → {ex}", "err")
                    except Exception:
                        self._errors += 1
                        self._log(f"ERROR (dir): {dpath} → {ex}", "err")
            self._log(f"  Removed {removed:,} directories"
                      + (" (root folder kept)" if keep_root else "")
                      + ".", "info")
        except Exception as ex:
            self._log(f"CRITICAL ERROR (directories): {ex}", "err")

        self.after(0, self._finish_delete)

    def _run_delete_list(self, files, dirs, threads):
        """Deletes an explicit list: files in parallel, folders via rmtree."""
        try:
            self._log(f"  Step 1/2: deleting {len(files):,} files…", "info")
            with ThreadPoolExecutor(max_workers=threads) as ex:
                futures = {ex.submit(self._delete_one_file, f): f
                           for f in files}
                done = 0
                for fut in as_completed(futures):
                    ok, size, errmsg = fut.result()
                    done += 1
                    if ok:
                        self._deleted    += 1
                        self._total_size += size
                    else:
                        if errmsg:
                            self._errors += 1
                            if self._errors < 50:
                                self._log(f"ERROR: {errmsg}", "err")
                            elif self._errors == 50:
                                self._log("(further errors not logged)",
                                          "info")
                    if done % 2000 == 0:
                        self._log(f"  … {self._deleted:,} files  "
                                  f"{self._fmt(self._total_size)}", "info")
        except Exception as ex:
            self._log(f"CRITICAL ERROR (files): {ex}", "err")

        if self._stop_event.is_set():
            self.after(0, self._finish_delete)
            return

        # folders from the list — full rmtree for each
        if dirs:
            self._log(f"  Step 2/2: deleting {len(dirs):,} folders "
                      f"(rmtree)…", "info")
            for dpath, _ in dirs:
                if self._stop_event.is_set():
                    break
                lpath = _long_path(dpath)
                try:
                    shutil.rmtree(lpath, ignore_errors=False)
                except Exception as ex:
                    try:
                        shutil.rmtree(lpath, ignore_errors=True)
                    except Exception:
                        pass
                    if os.path.exists(lpath):
                        self._errors += 1
                        self._log(f"ERROR (folder): {dpath} → {ex}", "err")

        self.after(0, self._finish_delete)

    def _tick_delete(self):
        if self._phase == "deleting":
            elapsed = time.time() - self._t0
            speed = self._deleted / elapsed if elapsed > 0 else 0
            self.lbl_deleted.config(
                text=f"{self._deleted:,}".replace(",", " "), fg=GREEN)
            self.lbl_freed.config(text=self._fmt(self._total_size))
            self.lbl_errors.config(
                text=f"{self._errors:,}".replace(",", " "),
                fg=RED if self._errors else FG)
            self.lbl_speed.config(text=f"{speed:.0f}/s")
            self.after(300, self._tick_delete)

    def _finish_delete(self):
        self.progress.stop()
        elapsed = time.time() - self._t0
        self.lbl_deleted.config(
            text=f"{self._deleted:,}".replace(",", " "), fg=GREEN)
        self.lbl_freed.config(text=self._fmt(self._total_size))
        self.lbl_errors.config(
            text=f"{self._errors}",
            fg=RED if self._errors else FG)
        speed = self._deleted / elapsed if elapsed > 0 else 0
        self.lbl_speed.config(text=f"{speed:.0f}/s")
        mode = self.mode_var.get()
        stopped = self._stop_event.is_set()
        self._log(
            f"══ FINISH  Deleted: {self._deleted:,}  "
            f"Errors: {self._errors}  "
            f"Freed: {self._fmt(self._total_size)}  "
            f"Time: {elapsed:.1f}s  "
            f"Avg: {speed:.0f}/s"
            + ("  [INTERRUPTED]" if stopped else ""), "hdr")
        self._set_phase("done")
        self.lbl_status.config(
            text=f"Done. Deleted {self._deleted:,} files "
                 f"in {elapsed:.1f}s.", fg=GREEN)
        self._save_log("usuwanie", {
            "Mode":                 mode,
            "Directory":            self.dir_var.get() or "(N/D)",
            "Pattern":              (self.pat_var.get()
                                      if mode == MODE_PATTERN else "(N/A)"),
            "Keep folder":          ("YES" if self.keep_root_var.get()
                                      and mode == MODE_FOLDER else "NO"),
            "Files deleted":        f"{self._deleted:,}",
            "Errors":                str(self._errors),
            "Space freed":          self._fmt(self._total_size),
            "Deletion time":        f"{elapsed:.1f} s",
            "Average speed":        f"{speed:.0f} files/s",
            "Interrupted":          "YES" if stopped else "NO",
        })
        self._found_files = []
        self._found_dirs  = []


# ═════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════
def main():
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    app = FileDeleterApp(initial_args=args)
    app.mainloop()


if __name__ == "__main__":
    main()