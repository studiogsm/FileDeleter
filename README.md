# 🗑️ File Deleter

**Fast bulk file deletion tool with scan-before-delete workflow**

Developed by [Laboratorium Elektroniki](https://laboratorium-elektroniki.pl) — Krystian Zarzecki

---

## Overview

File Deleter is a lightweight Windows desktop utility for deleting large numbers of files matching a given name pattern (wildcards supported). It was created to handle real-world scenarios such as removing millions of temporary log files from application directories — including protected locations like `C:\Program Files\`.

Key design goals:
- **Scan first, delete second** — always preview what will be deleted before committing
- **Multi-threaded deletion** — faster throughput especially on SSD/NVMe drives
- **UAC elevation** — automatic Administrator privilege request at startup
- **Session logs** — every scan and delete operation is saved to a `.txt` log file

---

## Features

- 📁 Directory browser with recursive subdirectory support
- 🔍 Wildcard pattern matching (e.g. `LOG.old.*`, `*.tmp`, `debug_*.log`)
- 👁️ **Scan phase** — counts files and total size before any deletion
- 🗑️ **Delete phase** — multi-threaded, configurable thread count (1–64)
- 🛡️ Auto UAC elevation — works on protected directories (`Program Files`, etc.)
- 📊 Live statistics — scanned / found / deleted / freed space / files per second
- ⏹️ Stop button — safely interrupt any operation mid-way
- 📝 Automatic log files saved to `FileDeleter_Logs\` folder next to the executable

---

## Screenshots

> *Coming soon*

---

## Requirements

- Windows 10 / 11
- Python 3.9+ (to run from source)
- `tkinter` — included with standard Python on Windows

---

## Usage

### Run from source

```bash
python file_deleter_v1.3_EN.py
```

### Compile to standalone EXE

1. Install PyInstaller:
   ```bash
   pip install pyinstaller
   ```
2. Run the included build script:
   ```bash
   BUILD.bat
   ```
   The compiled executable will appear in `dist\FileDeleter_v1.3.exe`.

> **Note:** The `BUILD.bat` script includes the `--uac-admin` flag so the compiled `.exe` automatically requests Administrator privileges via Windows UAC on launch.

---

## How to use

1. **Select directory** — click *Browse…* or type the path directly
2. **Enter pattern** — e.g. `LOG.old.*` to match all files starting with `LOG.old.`
3. Click **🔍 SCAN** — the tool counts matching files and their total size (nothing is deleted yet)
4. Review the results in the stats bar
5. Click **🗑 DELETE ALL** — confirm the dialog, deletion starts immediately
6. A log file is saved automatically to `FileDeleter_Logs\` when each phase completes

### Pattern examples

| Pattern | Matches |
|---|---|
| `LOG.old.*` | `LOG.old.1748293847`, `LOG.old.1748293900`, … |
| `*.tmp` | All `.tmp` files |
| `debug_*.log` | `debug_2024.log`, `debug_app.log`, … |
| `*` | Every file in the directory |

---

## Log files

After each scan and delete session, a log file is saved automatically:

```
FileDeleter_Logs\
  log_scan_2025-04-20_14-32-11.txt
  log_delete_2025-04-20_14-33-05.txt
```

Each log contains:
- Session summary (directory, pattern, file count, size, time, errors)
- Full operation log with timestamps

---

## Performance notes

Deletion speed depends primarily on the storage device:

| Drive type | Expected speed |
|---|---|
| HDD (5400/7200 RPM) | ~500–1 500 files/s |
| SATA SSD | ~2 000–5 000 files/s |
| NVMe SSD | ~5 000–15 000+ files/s |

For HDD, increasing thread count above 4 offers little benefit due to seek time limitations. For SSD/NVMe, try 16–32 threads for best throughput.

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
