# Installation Guide for Moxa Upload Script

This guide covers how to set up the Moxa Upload Script on a Windows machine.

## Prerequisites

- **Windows 10 or later** (for full Windows API support)
- **Python 3.8 or later** — [Download from python.org](https://www.python.org/downloads/)
  - **Important**: During installation, check the box "Add Python to PATH"

## Quick Start (Windows)

1. Open **Command Prompt** (Win + R, type `cmd`, press Enter)
2. Navigate to the project folder:
   ```cmd
   cd "path\to\MoxaUpload_Script"
   ```
3. Run the setup script:
   ```cmd
   setup.bat
   ```

That's it! The script will automatically:
- Detect Python
- Verify version (3.8+)
- Upgrade pip
- Install all dependencies
- Show you next steps

## Manual Installation (Fallback)

If the batch script doesn't work, install manually:

```cmd
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Troubleshooting

### "Python is not installed or not in PATH"
- Make sure Python is installed and restart your terminal
- If you installed Python recently, you may need to add it manually to PATH

### Installation errors or "Permission denied"
- The script automatically tries user-level installation first
- If that fails, run CMD **as Administrator**:
  - Right-click cmd.exe → "Run as administrator"
  - Then run `setup.bat` again

### "OSError" or "Long Path" errors during PySide6 installation
- **This is a Windows + Microsoft Store Python limitation**, not a blocker
- The setup script handles this automatically by:
  - Using `--no-cache-dir` flag to reduce path depths
  - Checking if core PySide6 is still usable even if some QML components fail
- **The script will succeed** even if you see these errors — the core GUI will work fine
- If setup reports "[OK] Core packages are available", you're good to go!

### Can't run `setup.bat` — "script is disabled"
- PowerShell execution policy issue
- Solution: Run with admin CMD (not PowerShell) — see instructions above

## After Installation

Once setup is complete, you can run:

### GUI Mode (Recommended for most users)
```cmd
python moxa_gui.py
```
This opens an interactive graphical interface for managing devices and running uploads.

### CLI Mode (Command-line)
```cmd
python upload_moxa.py <device_name> [options]
```

**Example:**
```cmd
python upload_moxa.py 1A-RIO-SDT-06A-1 --dry-run
```

### CLI Help
```cmd
python upload_moxa.py --help
```

## What Gets Installed

The setup script installs the following Python packages:

- **PySide6** (≥6.5.0) — GUI framework for the graphical interface

All other dependencies (CSV parsing, networking, etc.) are part of Python's standard library.

## Next Steps

1. **Read the main README.md** for detailed usage instructions
2. **Start the GUI**: `python moxa_gui.py` to add or edit devices
3. **Run a dry-run first**: `python upload_moxa.py <device_name> --dry-run` to test

## Support

If you encounter issues:
1. Make sure Python 3.8+ is installed: `python --version`
2. Verify requirements are installed: `python -m pip list | findstr PySide6`
3. Try running with administrator privileges
4. Check that all files are in the same directory (upload_moxa.py, moxa_gui.py, etc.)
