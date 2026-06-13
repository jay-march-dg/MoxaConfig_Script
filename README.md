# Moxa Upload Automation

**Purpose**: Upload a device configuration template to a Moxa E1210-series device, trigger a restart, and verify the device responds at its configured IP.

## Quick Start

### 1. Install Dependencies
Run the setup script once:
```cmd
setup.bat
```

This installs Python dependencies automatically. See [SETUP_INSTRUCTIONS.md](SETUP_INSTRUCTIONS.md) for details.

### 2. Run the GUI (Recommended)
```cmd
python moxa_gui.py
```

The GUI provides an easy-to-use interface to:
- ✅ View and manage the device list
- ✅ Upload configurations to devices
- ✅ Configure adapter settings
- ✅ View upload logs and status

### 3. Or Use Command-Line (Advanced)
For scripting or automation, use the CLI:
```cmd
python upload_moxa.py DEVICE_NAME [options]
```

## Files

- **`moxa_gui.py`** — GUI application (recommended for most users)
- **`upload_moxa.py`** — CLI automation script (for advanced/scripted use)
- **`deviceList.csv`** — Device inventory (columns: `device_name,device_type,ip_address`)
- **`Moxa-Template-<device_type>.txt`** — Configuration template (e.g., `Moxa-Template-1210.txt`)
- **`setup.bat`** — Automated setup script (run once to install dependencies)
- **`requirements.txt`** — Python package dependencies

## Prerequisites

- **Windows 10 or later**
- **Python 3.8 or later** (install from [python.org](https://www.python.org/downloads/))
  - Check "Add Python to PATH" during installation
- **Administrator privileges** (for network adapter configuration via `netsh`)
  - Can be skipped with `--rdp` or `--skip-adapter-change` flags

## How It Works

The upload process:
1. Reads the target device from `deviceList.csv` by device name
2. Loads the template file `Moxa-Template-<device_type>.txt`
3. Rewrites IPs in the template from the default subnet (192.168.127.0/24) to match the device's target subnet:
   - `.254` host in template → device IP (e.g., `192.168.127.254` → `10.1.54.30`)
   - `.1` host in template → gateway IP (e.g., `192.168.127.1` → `10.1.54.1`)
4. Temporarily configures laptop adapter to reach device on its default IP
5. Uploads rewritten template via multipart POST
6. Triggers device restart and waits for reboot
7. Reconfigures adapter to reach device on its new IP
8. Verifies device is responsive

## Configuration

### Device List (deviceList.csv)

Required columns: `device_name`, `device_type`, `ip_address`

Example:
```csv
device_name,device_type,ip_address
1A-RIO-SDT-06A-1,1210,10.1.54.30
1A-RIO-SDT-06A-2,1210,10.1.54.31
```

The gateway is automatically derived as `.1` on the device's subnet (e.g., `10.1.54.1`).

### Template Files

- Filename format: `Moxa-Template-<device_type>.txt` (e.g., `Moxa-Template-1210.txt`)
- Template should use default subnet IPs (192.168.127.x) for fields that need rewriting
- The script will rewrite these to match the target device's subnet

### Authentication

If the device requires a web password:
- **GUI**: Enter password in the interface when prompted
- **CLI**: Use `--password` flag (default is `moxa`)

## Command-Line Usage (Advanced)

For scripting or automation, use the CLI directly:

### Dry-run (recommended first):
```cmd
python upload_moxa.py 1A-RIO-SDT-06A-1 --dry-run
```

### Normal run:
```cmd
python upload_moxa.py 1A-RIO-SDT-06A-1
```

### Skip adapter changes (if already on correct subnet):
```cmd
python upload_moxa.py 1A-RIO-SDT-06A-1 --skip-adapter-change
```

### RDP-safe mode (no adapter changes):
```cmd
python upload_moxa.py 1A-RIO-SDT-06A-1 --rdp
```

### Upload to device IP instead of default IP:
```cmd
python upload_moxa.py 1A-RIO-SDT-06A-1 --a2
```

### With custom password:
```cmd
python upload_moxa.py 1A-RIO-SDT-06A-1 --password mypassword
```

### See all options:
```cmd
python upload_moxa.py --help
```

## Environment Variables

For advanced configuration (CLI mode):
- `MOXA_ADAPTER_NAME`: Windows adapter name (default: `Ethernet`)
- `MOXA_RDP_MODE`: Set to `1` to prevent adapter changes
- `MOXA_NETWORK_SETTLE_TIME`: Seconds to wait after changing adapter IP (default: `6`)
- `MOXA_POST_RESTART_WAIT`: Seconds to wait after restart before polling (default: `4`)
- `MOXA_POLL_INTERVAL`: Seconds between device polling attempts (default: `5`)
- `MOXA_POLL_TIMEOUT`: Max seconds to wait for device to be reachable (default: `180`)
- `MOXA_PASSWORD`: Default web password (default: `moxa`)

## Troubleshooting

### General Issues

**"Python is not installed or not found"**
- Install Python 3.8+ from [python.org](https://www.python.org/downloads/)
- Make sure "Add Python to PATH" is checked during installation
- Restart your terminal after installing

**"ModuleNotFoundError: No module named 'PySide6'"**
- Run `setup.bat` to install dependencies
- Or manually run: `python -m pip install PySide6`

**"Permission denied" or adapter configuration fails**
- Run Command Prompt as Administrator
- Or use `--skip-adapter-change` or `--rdp` flags to skip adapter changes

### Device Upload Issues

**Device returns 401/403 error**
- The device may require authentication
- Verify the password is correct (default is `moxa`)
- Try uploading through the web UI first to confirm connectivity

**Device not reachable after upload**
- Check that the adapter is properly configured for the target subnet
- Verify the device IP in `deviceList.csv` is correct
- Allow more time for the device to boot (check device LED status)

**Upload page doesn't show token field**
- Device firmware may have different format
- Try uploading through web UI first
- Check that the correct template file is being used

## Safety Notes

- ⚠️ The device **will reboot** after configuration upload
- ⚠️ Perform uploads during a **maintenance window**
- ⚠️ Ensure the template is in the **correct format** for your device
- ⚠️ The script requires **administrator privileges** to change network adapter settings
  - Can be skipped with `--rdp` or `--skip-adapter-change` if your adapter is already on the correct subnet

## Support & Documentation

- See [SETUP_INSTRUCTIONS.md](SETUP_INSTRUCTIONS.md) for installation help
- Run `python upload_moxa.py --help` for CLI documentation
- Check device LED status and web interface if uploads fail
