import os
import sys
import fnmatch
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
from pathlib import Path
import time
import ctypes

VERSION  = "v1.3"

# ── Auto-escalation of UAC privileges ───────────────────────────────────────
def _require_admin():
    """If the program lacks administrator rights, re-launch with UAC elevation."""
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        is_admin = False
    if not is_admin:
        # ShellExecute with "runas" triggers the UAC dialog
        params = " ".join(f'"{a}"' for a in sys.argv)
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1)
        if ret <= 32:
            # UAC rejected or error — run without elevation
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
BORDER  = "#3a3f50"
FONT_MONO = ("Consolas", 9)
FONT_UI   = ("Segoe UI", 9)
FONT_H    = ("Segoe UI Semibold", 10)
FONT_BIG  = ("Segoe UI Semibold", 13)

class FileDeleterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(820, 600)
        self.geometry("960x680")

        self._stop_event   = threading.Event()
        self._worker       = None
        self._deleted      = 0
        self._errors       = 0
        self._scanned      = 0
        self._total_size   = 0
        self._running      = False
        self._phase        = "idle"   # idle | scanning | ready | deleting | done
        self._found_files  = []       # list of (path, size) from scan
        self._found_size   = 0
        self._t0           = 0.0

        self._build_ui()
        self._center()
        self._set_phase("idle")

    # ──────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # accent bar
        tk.Frame(self, bg=ACCENT, height=4).pack(fill="x")

        # title bar
        hdr = tk.Frame(self, bg=BG2, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⬡  FILE DELETER", font=("Segoe UI Semibold", 14),
                 bg=BG2, fg=ACCENT2).pack(side="left", padx=18)
        tk.Label(hdr, text=VERSION, font=FONT_UI, bg=BG2, fg=FG2).pack(side="left")
        tk.Label(hdr, text="Laboratorium Elektroniki", font=FONT_UI,
                 bg=BG2, fg=FG2).pack(side="right", padx=18)

        body = tk.Frame(self, bg=BG, padx=18, pady=12)
        body.pack(fill="both", expand=True)

        # ── Directory
        tk.Label(body, text="Target directory", font=FONT_H, bg=BG, fg=FG).pack(anchor="w")
        row1 = tk.Frame(body, bg=BG)
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
        tk.Label(body, text="File name pattern  (e.g. LOG.old.* or *.tmp)",
                 font=FONT_H, bg=BG, fg=FG).pack(anchor="w")
        self.pat_var = tk.StringVar(value="LOG.old.*")
        tk.Entry(body, textvariable=self.pat_var, font=FONT_MONO,
                 bg=BG3, fg=ACCENT2, insertbackground=FG2, relief="flat",
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(fill="x", pady=(4, 8), ipady=6)

        # ── Options
        opt = tk.Frame(body, bg=BG)
        opt.pack(fill="x", pady=(0, 10))
        self.recurse_var = tk.BooleanVar(value=True)
        self.threads_var = tk.IntVar(value=8)
        for var, lbl in [(self.recurse_var, "Subdirectories (recursive)")]:
            tk.Checkbutton(opt, text=f"  {lbl}", variable=var, font=FONT_UI,
                           bg=BG, fg=FG, selectcolor=BG3, activebackground=BG,
                           activeforeground=ACCENT2, highlightthickness=0,
                           cursor="hand2").pack(side="left", padx=(0, 20))
        tk.Label(opt, text="Threads:", font=FONT_UI, bg=BG, fg=FG2).pack(side="left")
        self.threads_spin = tk.Spinbox(opt, from_=1, to=64, textvariable=self.threads_var,
                                        width=4, font=FONT_UI, bg=BG3, fg=FG,
                                        buttonbackground=BG3, relief="flat",
                                        highlightthickness=1,
                                        highlightbackground=BORDER)
        self.threads_spin.pack(side="left", padx=(4, 20))
        tk.Label(opt, text="(more threads = faster deletion on SSD)",
                 font=("Segoe UI", 8), bg=BG, fg=FG2).pack(side="left")

        # ── Stats bar
        stats = tk.Frame(body, bg=BG3, pady=6, padx=12,
                         highlightthickness=1, highlightbackground=BORDER)
        stats.pack(fill="x", pady=(0, 8))
        self.lbl_scanned = self._stat_cell(stats, "Scanned", "—")
        self._vsep(stats)
        self.lbl_found   = self._stat_cell(stats, "Found", "—")
        self._vsep(stats)
        self.lbl_found_sz= self._stat_cell(stats, "To delete", "—")
        self._vsep(stats)
        self.lbl_deleted = self._stat_cell(stats, "Deleted", "—")
        self._vsep(stats)
        self.lbl_freed   = self._stat_cell(stats, "Freed", "—")
        self._vsep(stats)
        self.lbl_errors  = self._stat_cell(stats, "Errors", "—")
        self._vsep(stats)
        self.lbl_speed   = self._stat_cell(stats, "Files/s", "—")

        # ── Progress
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Del.Horizontal.TProgressbar",
                        troughcolor=BG3, background=ACCENT,
                        bordercolor=BG3, lightcolor=ACCENT2, darkcolor=ACCENT)
        self.progress = ttk.Progressbar(body, style="Del.Horizontal.TProgressbar",
                                         mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 6))

        # ── Buttons — pakowane PRZED logiem, żeby expand=True loga ich nie przykryło
        br = tk.Frame(body, bg=BG)
        br.pack(fill="x", side="bottom", pady=(8, 0))

        # ── Log (pakowane po przyciskach, expand zajmuje pozostałą przestrzeń)
        tk.Label(body, text="Operation log", font=FONT_H, bg=BG, fg=FG2).pack(anchor="w")
        lf = tk.Frame(body, bg=BG3, highlightthickness=1, highlightbackground=BORDER)
        lf.pack(fill="both", expand=True, pady=(4, 0))
        self.log = tk.Text(lf, font=FONT_MONO, bg=BG3, fg=FG2,
                            insertbackground=FG, relief="flat",
                            wrap="none", state="disabled",
                            selectbackground=BG, selectforeground=ACCENT2)
        sbv = tk.Scrollbar(lf, orient="vertical",   command=self.log.yview, bg=BG3)
        sbh = tk.Scrollbar(lf, orient="horizontal", command=self.log.xview, bg=BG3)
        self.log.configure(yscrollcommand=sbv.set, xscrollcommand=sbh.set)
        self.log.tag_config("ok",   foreground=GREEN)
        self.log.tag_config("err",  foreground=RED)
        self.log.tag_config("info", foreground=YELLOW)
        self.log.tag_config("hdr",  foreground=ACCENT2)
        sbv.pack(side="right", fill="y")
        sbh.pack(side="bottom", fill="x")
        self.log.pack(fill="both", expand=True)

        # przyciski definiujemy tu (po br), ale br już jest spakowany wyżej

        self.btn_scan = tk.Button(br, text="🔍  SCAN",
                                   font=("Segoe UI Semibold", 10),
                                   bg="#2563eb", fg="white",
                                   activebackground="#1d4ed8", activeforeground="white",
                                   relief="flat", cursor="hand2", padx=22, pady=7,
                                   command=self._start_scan)
        self.btn_scan.pack(side="left", padx=(0, 8))

        self.btn_delete = tk.Button(br, text="🗑  DELETE ALL",
                                     font=("Segoe UI Semibold", 10),
                                     bg=ACCENT, fg="white",
                                     activebackground=ACCENT2, activeforeground="white",
                                     relief="flat", cursor="hand2", padx=22, pady=7,
                                     command=self._start_delete)
        self.btn_delete.pack(side="left", padx=(0, 8))

        self.btn_stop = tk.Button(br, text="■  STOP",
                                   font=("Segoe UI Semibold", 10),
                                   bg=BG3, fg=FG2,
                                   activebackground=RED, activeforeground="white",
                                   relief="flat", cursor="hand2", padx=22, pady=7,
                                   state="disabled",
                                   command=self._stop)
        self.btn_stop.pack(side="left", padx=(0, 8))

        tk.Button(br, text="Clear log", font=FONT_UI, bg=BG3, fg=FG2,
                  activebackground=BG2, activeforeground=FG,
                  relief="flat", cursor="hand2", padx=12, pady=7,
                  command=self._clear_log).pack(side="left")

        self.lbl_status = tk.Label(br, text="Ready.", font=FONT_UI, bg=BG, fg=FG2)
        self.lbl_status.pack(side="right", padx=4)

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _stat_cell(self, p, lbl, val):
        f = tk.Frame(p, bg=BG3)
        f.pack(side="left", expand=True)
        tk.Label(f, text=lbl, font=("Segoe UI", 8), bg=BG3, fg=FG2).pack()
        w = tk.Label(f, text=val, font=FONT_BIG, bg=BG3, fg=FG)
        w.pack()
        return w

    def _vsep(self, p):
        tk.Frame(p, bg=BORDER, width=1).pack(side="left", fill="y", padx=6, pady=4)

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

    # ── Save log to file ─────────────────────────────────────────────────────
    def _get_log_dir(self):
        """Log directory: next to EXE/script, subdirectory FileDeleter_Logs."""
        base = os.path.dirname(os.path.abspath(sys.argv[0]))
        log_dir = os.path.join(base, "FileDeleter_Logs")
        os.makedirs(log_dir, exist_ok=True)
        return log_dir

    def _save_log(self, session_type: str, summary: dict):
        """Saves session log to a TXT file with date/time in the filename."""
        ts      = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        fname   = f"log_{session_type}_{ts}.txt"
        fpath   = os.path.join(self._get_log_dir(), fname)
        lines   = []
        lines.append("=" * 70)
        lines.append(f"  Laboratorium Elektroniki — File Deleter {VERSION}")
        lines.append(f"  Session: {session_type.upper()}   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 70)
        for k, v in summary.items():
            lines.append(f"  {k:<28} {v}")
        lines.append("-" * 70)
        lines.append("  DETAILS (from log window):")
        lines.append("-" * 70)
        # get full text from log widget
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
            self._log(f"Failed to save log: {ex}", "err")

    # ── Phase state machine ────────────────────────────────────────────────────
    def _set_phase(self, phase):
        self._phase = phase
        if phase == "idle":
            self.btn_scan.config(state="normal")
            self.btn_delete.config(state="disabled")
            self.btn_stop.config(state="disabled")
        elif phase == "scanning":
            self.btn_scan.config(state="disabled")
            self.btn_delete.config(state="disabled")
            self.btn_stop.config(state="normal")
        elif phase == "ready":
            self.btn_scan.config(state="normal")   # allow re-scan
            self.btn_delete.config(state="normal")
            self.btn_stop.config(state="disabled")
        elif phase == "deleting":
            self.btn_scan.config(state="disabled")
            self.btn_delete.config(state="disabled")
            self.btn_stop.config(state="normal")
        elif phase == "done":
            self.btn_scan.config(state="normal")
            self.btn_delete.config(state="disabled")
            self.btn_stop.config(state="disabled")

    # ── Browse ─────────────────────────────────────────────────────────────────
    def _browse(self):
        d = filedialog.askdirectory(title="Select directory")
        if d:
            self.dir_var.set(d.replace("/", "\\"))
            self._set_phase("idle")
            self._found_files = []

    # ── Stop ───────────────────────────────────────────────────────────────────
    def _stop(self):
        self._stop_event.set()
        self.lbl_status.config(text="Stopping…", fg=YELLOW)

    # ══════════════════════════════════════════════════════════════════════════
    #  PHASE 1: SCAN
    # ══════════════════════════════════════════════════════════════════════════
    def _start_scan(self):
        directory = self.dir_var.get().strip()
        pattern   = self.pat_var.get().strip()
        if not directory or not os.path.isdir(directory):
            messagebox.showerror("Error", "Please enter a valid directory.")
            return
        if not pattern:
            messagebox.showwarning("No pattern", "Please enter a file name pattern.")
            return

        self._found_files = []
        self._found_size  = 0
        self._scanned     = 0
        self._stop_event.clear()
        self._t0 = time.time()
        self._set_phase("scanning")
        self.progress.start(10)
        self.lbl_status.config(text="Scanning…", fg=YELLOW)
        self.lbl_found.config(text="…", fg=YELLOW)
        self._log(f"══ SCANNING  directory: {directory}  pattern: {pattern}", "hdr")

        threading.Thread(
            target=self._run_scan,
            args=(directory, pattern, self.recurse_var.get()),
            daemon=True).start()
        self.after(300, self._tick_scan)

    def _run_scan(self, directory, pattern, recurse):
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
            self._log(f"BŁĄD skanowania: {ex}", "err")
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
        n  = len(self._found_files)
        sz = self._found_size
        self.lbl_scanned.config(
            text=f"{self._scanned:,}".replace(",", " "), fg=FG)
        self.lbl_found.config(
            text=f"{n:,}".replace(",", " "),
            fg=GREEN if n else FG2)
        self.lbl_found_sz.config(text=self._fmt(sz))
        self.lbl_deleted.config(text="—", fg=FG)
        self.lbl_freed.config(text="—")
        self.lbl_errors.config(text="—", fg=FG)
        self.lbl_speed.config(text="—")

        if self._stop_event.is_set():
            self._log("Scan aborted by user.", "info")
            self._set_phase("idle")
            self.lbl_status.config(text="Aborted.", fg=YELLOW)
        else:
            self._log(
                f"Scan complete: scanned {self._scanned:,} files, "
                f"found {n:,} matches ({self._fmt(sz)}), "
                f"time: {elapsed:.1f}s", "ok")
            if n == 0:
                self._log("No files to delete.", "info")
                self._set_phase("idle")
                self.lbl_status.config(text="No matches found.", fg=FG2)
            else:
                self._set_phase("ready")
                self.lbl_status.config(
                    text=f"Ready to delete {n:,} files ({self._fmt(sz)}).",
                    fg=YELLOW)
                self._save_log("scan", {
                    "Directory":            self.dir_var.get(),
                    "Pattern":              self.pat_var.get(),
                    "Files scanned":        f"{self._scanned:,}",
                    "Files found":          f"{n:,}",
                    "Total size":           self._fmt(sz),
                    "Scan time":            f"{elapsed:.1f} s",
                })

    # ══════════════════════════════════════════════════════════════════════════
    #  PHASE 2: DELETE
    # ══════════════════════════════════════════════════════════════════════════
    def _start_delete(self):
        if not self._found_files:
            messagebox.showinfo("No files", "Please run a scan first.")
            return
        n = len(self._found_files)
        sz = self._fmt(self._found_size)
        if not messagebox.askyesno(
                "Confirmation",
                f"Are you sure you want to delete {n:,} files ({sz})?\n\nThis action cannot be undone!"):
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
        self._log(
            f"══ DELETING  {n:,} files  threads: {threads}", "hdr")

        threading.Thread(
            target=self._run_delete,
            args=(list(self._found_files), threads),
            daemon=True).start()
        self.after(300, self._tick_delete)

    def _delete_one(self, item):
        path, size = item
        if self._stop_event.is_set():
            return False, 0, ""
        try:
            os.remove(path)
            return True, size, ""
        except Exception as ex:
            return False, 0, f"{path} → {ex}"

    def _run_delete(self, files, threads):
        try:
            with ThreadPoolExecutor(max_workers=threads) as ex:
                futures = {ex.submit(self._delete_one, f): f for f in files}
                done = 0
                for fut in as_completed(futures):
                    ok, size, errmsg = fut.result()
                    done += 1
                    if ok:
                        self._deleted    += 1
                        self._total_size += size
                    else:
                        if errmsg:                  # not just stopped
                            self._errors += 1
                            self._log(f"ERROR: {errmsg}", "err")
                    if done % 1000 == 0:
                        self._log(
                            f"  … {self._deleted:,} deleted  "
                            f"{self._fmt(self._total_size)}", "info")
        except Exception as ex:
            self._log(f"CRITICAL ERROR: {ex}", "err")
        finally:
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
        self._found_files = []
        stopped = self._stop_event.is_set()
        self._log(
            f"══ DONE  Deleted: {self._deleted:,}  Errors: {self._errors}  "
            f"Freed: {self._fmt(self._total_size)}  "
            f"Time: {elapsed:.1f}s  "
            f"Avg: {speed:.0f} files/s"
            + ("  [ABORTED]" if stopped else ""), "hdr")
        self._set_phase("done")
        self.lbl_status.config(
            text=f"Done. Deleted {self._deleted:,} files in {elapsed:.1f}s.",
            fg=GREEN)
        self._save_log("delete", {
            "Directory":            self.dir_var.get(),
            "Pattern":              self.pat_var.get(),
            "Files deleted":        f"{self._deleted:,}",
            "Errors":                str(self._errors),
            "Space freed":          self._fmt(self._total_size),
            "Delete time":          f"{elapsed:.1f} s",
            "Average speed":        f"{speed:.0f} files/s",
            "Aborted by user":      "YES" if stopped else "NO",
        })


if __name__ == "__main__":
    app = FileDeleterApp()
    app.mainloop()
