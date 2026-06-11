# Moxa Upload Automation

**Overview**
- **Purpose**: Upload a device configuration template to a Moxa E1210-series device, trigger a restart, and verify the device responds at its configured IP.
- **Script**: `upload_moxa.py` — performs template rewrite, adapter IP reconfiguration, multipart POST to the device upload form, restart, and verification.

**Files**
- **Script**: `upload_moxa.py` — main automation script.
- **Device list**: `deviceList.csv` — CSV of devices (columns: `device_name,device_type,ip_address`).
- **Template**: `Moxa-Template-<device_type>.txt` — required template file (for your devices: `Moxa-Template-1210.txt`).

**Prerequisites**
- Windows machine with administrative privileges to run `netsh` (unless you use `--rdp` or `--skip-adapter-change`).
- Python 3.8+ installed.
- The script and files are located together in the `MoxaUpload_Script` folder.

**How it works (high level)**
- Reads the target device from `deviceList.csv` by `device_name`.
- Loads the exact template file `Moxa-Template-<device_type>.txt`.
- Rewrites IPs in the template that are on the default template subnet (192.168.127.0/24) to match the device's subnet and IP:
  - Any `.254` host in the template becomes the device IP (e.g. `192.168.127.254` -> `10.1.54.30`).
  - The gateway is always set to host `.1` on the device subnet (e.g. `10.1.54.1`).
- Temporarily configures the laptop adapter to a safe host on the device subnet (default host `100`) so it can reach the device at its default IP `192.168.127.254`.
- Performs a `multipart/form-data` POST to the device upload endpoint (`06_5_1.htm`) with the rewritten template as `importfile` (the script first GETs the upload page `06_5.htm` to extract a `token`).
- Posts a restart request (default `09_1.htm`) and waits for the device to boot.
- Switches the laptop adapter to a host on the device's target subnet (so it can reach the device at its new IP) and polls for a successful GET.

**Upload modes**
- Default mode uploads to the device's default management IP `192.168.127.254`.
- `--a2` mode uploads to the device's configured IP from `deviceList.csv` instead of the default IP.
- In both modes, the laptop adapter is set to a different host on the same subnet as the target device IP.

**Authentication**
- The device may prompt for a password before allowing some pages or actions.
- Use `--password` to supply the web password if it is different from the default value.
- Default password value in the script is `moxa`.

**CSV format**
- Required columns: `device_name,device_type,ip_address`.
- Example row: `1A-RIO-SDT-06A-1,1210,10.1.54.30`.
- Note: The script derives gateway as host `1` of the device's subnet; do not rely on a `gateway` column unless the script is updated.

**Template requirements**
- Filename must be exactly `Moxa-Template-<device_type>.txt` (e.g. `Moxa-Template-1210.txt`).
- The template should use the default template subnet `192.168.127.x` for network fields that need rewriting. The script replaces those values to match the device IP and gateway.

**Usage**
- Dry-run (recommended first):

```powershell
python upload_moxa.py 1A-RIO-SDT-06A-1 --dry-run
```

- Normal run (will attempt to change `netsh` adapter settings):

```powershell
python upload_moxa.py 1A-RIO-SDT-06A-1
```

- Skip adapter changes (useful if adapter already on correct subnet):

```powershell
python upload_moxa.py 1A-RIO-SDT-06A-1 --skip-adapter-change
```

- RDP-safe mode (skip adapter changes; equivalent to setting `MOXA_RDP_MODE=1`):

```powershell
python upload_moxa.py 1A-RIO-SDT-06A-1 --rdp
```

- Device IP upload mode with password explicitly set:

```powershell
python upload_moxa.py 4A-RIO-TX-M11-R11 --a2 --password moxa
```

- A2 mode (upload directly to the device IP instead of the default IP):

```powershell
python upload_moxa.py 1A-RIO-SDT-06A-1 --a2
```

**Environment variables**
- `MOXA_ADAPTER_NAME`: Windows adapter name (default `Ethernet`).
- `MOXA_RDP_MODE`: set to `1` to prevent adapter changes (alternate to `--rdp`).
- `MOXA_NETWORK_SETTLE_TIME`: seconds to wait after changing adapter IP (default `4`).
- `MOXA_POST_RESTART_WAIT`: seconds to wait after restart before polling (default `10`).

**Safety notes**
- The script uses `netsh` and requires administrative rights to change adapter settings unless using `--rdp`.
- The device will reboot after the upload; ensure this is performed during a maintenance window.
- The template must be in the correct device format; uploading an invalid template can leave the device improperly configured.

**Troubleshooting**
- If upload returns `401/403` the device requires authentication or the token/cookies didn't match. Use the web UI first to confirm the flow and capture cookies if needed.
- If device not reachable at new IP, check adapter IP, subnet mask, or the device boot progress.

If you want, I can add a small `requirements.txt`, an example template, and an integration test stub that runs `--dry-run` for a sample device.
