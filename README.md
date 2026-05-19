# File Deleter

**Fast bulk file deletion tool for Windows — pattern-based, folder-based, and clipboard-based workflows**

Developed by [Laboratorium Elektroniki](https://laboratoriumelektroniki.pl) — Krystian Zarzecki

---

## Overview

File Deleter is a Windows desktop utility for removing large numbers of files quickly — far faster than Windows Explorer, which slows to a crawl on tens of thousands of files. The tool was built to handle real forensic and developer scenarios: million-file log directories, deeply nested artifact trees, and selections that Explorer refuses to right-click on.

Three independent deletion workflows live in the same GUI:

1. **Pattern mode** — match files in a directory by wildcard (`*.tmp`, `LOG.old.*`, etc.)
2. **Folder mode** — wipe an entire folder and everything inside it, optionally keeping the empty root
3. **List mode** — load an explicit file list from the Windows clipboard (`Ctrl+C` in Explorer), drag-drop, or `Send To` menu — and delete only those items

All three modes share the same multi-threaded engine, scan-before-delete confirmation step, automatic UAC elevation, and full session logging.

---

## Key features

- **Three modes** — pattern matching, full-folder wipe, explicit list
- **Clipboard integration** — copy files in Explorer (`Ctrl+C`), then *Load from clipboard* in the app. Bypasses the Windows 32 000-character command-line limit, so it handles **millions of files** in one go
- **Right-click integration** — installs a *Delete with File Deleter* entry in the Windows context menu (folders + files) directly from the GUI
- **Send To integration** — installs a *FileDeleter* shortcut in the Windows `Send To` menu directly from the GUI
- **Long path support** — automatically applies the `\\?\` prefix so paths over the 260-character `MAX_PATH` limit work (extends to ~32 000 chars)
- **Scan before delete** — every operation previews counts and total size before any file is touched
- **Multi-threaded** — configurable thread count (1–64), defaults to 16 (good for SSD/NVMe)
- **Auto UAC elevation** — relaunches itself as administrator on startup so protected paths work
- **Session logs** — every scan and delete writes a timestamped `.txt` log to `FileDeleter_Logs\` next to the executable
- **Live statistics** — scanned / found / deleted / freed / errors / files-per-second update during the operation
- **Stop button** — safely interrupt at any point
- **Drag-drop / command-line arguments** — drop files or folders onto the `.exe` and they pre-populate the list

---

## Requirements

- Windows 10 / 11 (x64)
- Python 3.9+ (only when running from source)
- `tkinter` — included with standard Python on Windows
- PowerShell (built into Windows 10/11) — used by the *Send To* installer

---

## Installation

### Run from source

```
python file_deleter_v1.6_EN.py
```

### Compile to a standalone EXE

```
BUILD.bat
```

Requires Python in `PATH`. The script auto-installs PyInstaller if missing and produces `dist\FileDeleter.exe`.

The `BUILD.bat` script includes the `--uac-admin` flag, so the compiled `.exe` requests Administrator privileges via the Windows UAC prompt on launch.

After building, copy `FileDeleter.exe` to a stable location (for example `C:\Tools\FileDeleter\`) — the right-click and Send To registry entries embed the full path, so the executable should not be moved afterward.

---

## Usage

### Pattern mode (delete files matching a wildcard)

1. Choose **File pattern** in the mode selector
2. Click **Browse…** and select a directory
3. Type a pattern in the *Pattern* field (e.g. `*.tmp`, `LOG.old.*`, `cache_*.bin`)
4. Click **🔍 SCAN** — the tool walks the tree and counts matches
5. Click **🗑 DELETE ALL** — confirm the dialog, deletion starts

Wildcard examples:

| Pattern | Matches |
| --- | --- |
| `LOG.old.*` | `LOG.old.1748293847`, `LOG.old.1748293900`, … |
| `*.tmp` | all `.tmp` files |
| `debug_*.log` | `debug_2024.log`, `debug_app.log`, … |
| `*` | every file in the directory |

### Folder mode (wipe an entire folder)

1. Choose **Entire folder** in the mode selector
2. Click **Browse…** and select the folder to wipe
3. Optionally tick **Keep the folder itself** — only the contents are deleted, the empty root remains
4. Click **🔍 SCAN** — counts files, subfolders, and total size
5. Click **🗑 DELETE ALL** — files are deleted in parallel, then directories from deepest to shallowest

### List mode (delete an explicit selection — including 1 000 000 files)

This is the workflow for very large, hand-picked selections that Explorer refuses to right-click on (Windows hides custom context menus when more than ~15 files are selected).

1. In Windows Explorer, select the files you want to delete (any number — 1, 1 000, or 1 000 000)
2. Press **`Ctrl+C`** (copy)
3. Open **FileDeleter** — mode auto-switches to **List**
4. Click **📋 Load from clipboard** — all paths load instantly (clipboard is unaffected by the cmd-line limit)
5. Review the count and total size
6. Click **🗑 DELETE ALL** — confirm and delete

### Right-click integration

In the GUI:

- Click **➕ Add** next to *Context menu (right-click)*
- A *Delete with File Deleter* entry is added for both folders and files
- In Explorer, right-click a folder or single file → *Delete with File Deleter*

> **Windows 11 note:** custom menu entries appear under *Show more options* (or with `Shift+F10`) unless you use a third-party menu manager.
>
> **Multi-selection limit:** Windows hides custom context-menu entries when more than ~15 items are selected. For large selections, use **List mode + clipboard**.

### Send To integration

In the GUI:

- Click **➕ Add** next to *'Send To' menu*
- A *FileDeleter* shortcut is added to `%APPDATA%\Microsoft\Windows\SendTo`
- In Explorer, select files/folders → right-click → *Send To* → *FileDeleter*

`Send To` has no per-selection-size limit like the context menu, but it is still bound by the Windows command-line length limit (~32 000 characters), which works out to roughly 200 average paths. For larger selections, use **List mode + clipboard**.

### Drag-drop

Drag files or folders onto `FileDeleter.exe` — the GUI opens with the items pre-loaded in List mode.

---

## Log files

After each scan and delete session, a log file is saved to:

```
FileDeleter_Logs\
  log_skanowanie_2025-05-19_14-32-11.txt
  log_usuwanie_2025-05-19_14-33-05.txt
```

Each log contains a summary header (mode, directory, file count, size, time, errors) followed by the full timestamped operation log.

---

## Performance notes

Deletion speed depends primarily on the storage device:

| Drive type | Expected speed |
| --- | --- |
| HDD (5 400 / 7 200 RPM) | ~500–1 500 files/s |
| SATA SSD | ~2 000–5 000 files/s |
| NVMe SSD | ~5 000–15 000+ files/s |

For HDD, increasing thread count above 4 offers little benefit due to seek-time limits. For SSD / NVMe, 16–32 threads gives the best throughput. The default is 16.

---

## What's new in v1.6

Compared to v1.3 (the previous public release):

- New **Folder mode** — wipe entire folders multi-threaded, with an optional *keep the folder itself* switch
- New **List mode** — load file lists from the clipboard, drag-drop, or `Send To` menu
- Built-in **right-click context-menu installer** with one-click add/remove
- Built-in **Send To menu installer** with one-click add/remove
- **Long path support** — paths over 260 characters now work (`\\?\` prefix)
- **Command-line argument handling** — accepts paths via `argv`, auto-detects mode
- **64-bit-safe clipboard reads** — proper `ctypes` argtypes/restype for `HDROP` / `HANDLE`
- **Resilient mode switching** — pack-order fix so the *Pattern* field never disappears after mode toggles
- Larger default thread count (16 instead of 8) for modern SSDs
- Retry with `chmod` on `PermissionError` (clears the read-only attribute)
- Improved error throttling — after 50 errors the rest are counted but not logged, to keep the log readable on millions of files

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Author

**Krystian Zarzecki**
President of the Board — Wezafon Sp. z o.o. (brand: Laboratorium Elektroniki)
Court-appointed expert in digital forensics and teleinformatics
Mielec, Poland

---

*Part of the Laboratorium Elektroniki internal toolset.*
