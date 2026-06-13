from __future__ import annotations

import argparse
import csv
import hashlib
import json
import ipaddress
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener


SCRIPT_DIR = Path(__file__).resolve().parent
DEVICE_LIST_PATH = SCRIPT_DIR / "deviceList.csv"
DEFAULT_TEMPLATE_DIR = SCRIPT_DIR
SETTINGS_PATH = SCRIPT_DIR / "adapter_settings.json"

DEFAULT_DEVICE_IP = "192.168.127.254"
DEFAULT_SUBNET_MASK = "255.255.255.0"
DEFAULT_TEMPLATE_NETWORK = ipaddress.ip_network("192.168.127.0/24")

DEFAULT_UPLOAD_PAGE = "06_5.htm"
DEFAULT_UPLOAD_ACTION = "06_5_1.htm"
DEFAULT_RESTART_PAGE = "09.htm"
DEFAULT_RESTART_ACTION = "09_1.htm"

def load_settings() -> dict[str, str]:
	if not SETTINGS_PATH.exists():
		return {}
	try:
		return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return {}


def get_default_adapter_name() -> str:
	settings = load_settings()
	return settings.get("adapter_name") or os.environ.get("MOXA_ADAPTER_NAME", "Ethernet")


def save_adapter_name(adapter_name: str) -> None:
	SETTINGS_PATH.write_text(json.dumps({"adapter_name": adapter_name}, indent=2), encoding="utf-8")


ADAPTER_NAME = get_default_adapter_name()
RDP_MODE = os.environ.get("MOXA_RDP_MODE", "0").lower() in {"1", "true", "yes", "on"}
NETWORK_SETTLE_TIME = int(os.environ.get("MOXA_NETWORK_SETTLE_TIME", "6"))
POST_RESTART_WAIT = int(os.environ.get("MOXA_POST_RESTART_WAIT", "4"))
POLL_INTERVAL = int(os.environ.get("MOXA_POLL_INTERVAL", "5"))
POLL_TIMEOUT = int(os.environ.get("MOXA_POLL_TIMEOUT", "180"))
DEFAULT_ADAPTER_HOST = 100
DEFAULT_GATEWAY_HOST = 1
MOXA_PASSWORD = os.environ.get("MOXA_PASSWORD", "moxa")


def _print_header(title: str) -> None:
	print(f"\n{'=' * 50}")
	print(f"  {title}")
	print(f"{'=' * 50}\n")


def _print_kv(label: str, value: str, label_width: int = 14) -> None:
	print(f"  {label.ljust(label_width)} {value}")


def _tick(msg: str) -> None:
	print(f"  [OK] {msg}")


def _arrow(msg: str) -> None:
	print(f"  >> {msg}")


def _host_from_base(base: str) -> str:
	return base.split("//", 1)[1].rstrip("/").split("/")[0]


def _extract_adapter_name_from_argv(argv: list[str]) -> Optional[str]:
	if len(argv) < 3:
		return None

	first = argv[1].strip().lower()
	second = argv[2].strip().lower()
	if first == "set-adapter":
		parts = [part for part in argv[2:] if part not in {"=", ":"}]
		return " ".join(parts).strip() or None

	if first == "set" and second == "adapter":
		parts = [part for part in argv[3:] if part not in {"=", ":", "to"}]
		return " ".join(parts).strip() or None

	return None



@dataclass(frozen=True)
class DeviceRecord:
	device_name: str
	device_type: str
	ip_address: str
	gateway: Optional[str] = None


class MoxaUploadError(RuntimeError):
	pass


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Upload a Moxa config template to a device, reboot it, and verify the new IP."
	)
	parser.add_argument("device_name", help="Device name from deviceList.csv")
	parser.add_argument("--device-list", default=str(DEVICE_LIST_PATH), help="Path to deviceList.csv")
	parser.add_argument(
		"--template-dir", default=str(DEFAULT_TEMPLATE_DIR), help="Directory that holds template files"
	)
	parser.add_argument(
		"--template-file",
		default=None,
		help="Optional explicit template file path. Overrides template-dir lookup.",
	)
	parser.add_argument("--scheme", default="http", choices=("http", "https"), help="Device web scheme")
	parser.add_argument("--upload-page", default=DEFAULT_UPLOAD_PAGE, help="Upload form page path")
	parser.add_argument("--upload-action", default=DEFAULT_UPLOAD_ACTION, help="Upload form POST target")
	parser.add_argument("--restart-page", default=DEFAULT_RESTART_PAGE, help="Restart page path")
	parser.add_argument("--restart-action", default=DEFAULT_RESTART_ACTION, help="Restart POST target")
	parser.add_argument("--adapter-name", default=ADAPTER_NAME, help="Windows adapter name to reconfigure")
	parser.add_argument("--a2", action="store_true", help="Upload to the device IP instead of the default IP")
	parser.add_argument("--rdp", action="store_true", help="Skip adapter IP changes for remote/RDP runs")
	parser.add_argument("--skip-adapter-change", action="store_true", help="Do not change the Windows adapter IP")
	parser.add_argument("--password", default=MOXA_PASSWORD, help="Moxa web password")
	parser.add_argument("--debug-http", action="store_true", help="Print HTTP response snippets when requests fail")
	parser.add_argument("--dry-run", action="store_true", help="Print the plan without changing anything")
	return parser.parse_args()


def handle_set_adapter_command(argv: list[str]) -> int | None:
	adapter_name = _extract_adapter_name_from_argv(argv)
	if not adapter_name:
		return None

	save_adapter_name(adapter_name)
	print(f"Adapter name saved: {adapter_name}")
	print(f"Settings file: {SETTINGS_PATH}")
	print("Future runs will use this adapter name unless overridden with --adapter-name.")
	return 0


def load_device_record(device_list_path: Path, device_name: str) -> DeviceRecord:
	if not device_list_path.exists():
		raise MoxaUploadError(f"Device list not found: {device_list_path}")

	with device_list_path.open(newline="", encoding="utf-8-sig") as handle:
		reader = csv.DictReader(handle)
		required = {"device_name", "device_type", "ip_address"}
		missing = required.difference(reader.fieldnames or [])
		if missing:
			raise MoxaUploadError(
				f"deviceList.csv is missing required columns: {', '.join(sorted(missing))}"
			)

		for row in reader:
			if row.get("device_name", "").strip() != device_name:
				continue

			return DeviceRecord(
				device_name=row["device_name"].strip(),
				device_type=row["device_type"].strip(),
				ip_address=row["ip_address"].strip(),
				gateway=(row.get("gateway", "").strip() or None),
			)

	raise MoxaUploadError(f"Device not found in CSV: {device_name}")


def load_template_path(template_dir: Path, template_file: Optional[str], device: DeviceRecord) -> Path:
	if template_file:
		path = Path(template_file)
		if not path.is_absolute():
			path = (SCRIPT_DIR / path).resolve()
		if not path.exists():
			raise MoxaUploadError(f"Template file not found: {path}")
		return path

	if not template_dir.exists():
		raise MoxaUploadError(f"Template directory not found: {template_dir}")

	template_path = template_dir / f"Moxa-Template-{device.device_type}.txt"
	if template_path.exists():
		return template_path

	raise MoxaUploadError(
		f"Required template not found for device type {device.device_type}: {template_path}"
	)


def get_network(ip_address: str) -> ipaddress.IPv4Network:
	return ipaddress.ip_network(f"{ip_address}/{DEFAULT_SUBNET_MASK}", strict=False)


def choose_host_ip(network: ipaddress.IPv4Network, excluded_hosts: set[int], preferred: int, fallbacks: tuple[int, ...]) -> str:
	for host in (preferred, *fallbacks):
		if host in excluded_hosts:
			continue
		candidate_ip = ipaddress.ip_address(int(network.network_address) + host)
		if candidate_ip in network and candidate_ip != network.network_address and candidate_ip != network.broadcast_address:
			return str(candidate_ip)
	raise MoxaUploadError("Unable to choose a safe host IP on the target subnet")


def derive_gateway_ip(device: DeviceRecord) -> str:
	network = get_network(device.ip_address)
	return str(ipaddress.ip_address(int(network.network_address) + DEFAULT_GATEWAY_HOST))


def choose_laptop_ip(device: DeviceRecord) -> str:
	network = get_network(device.ip_address)
	device_host = int(device.ip_address.split(".")[-1])
	gateway_host = int(derive_gateway_ip(device).split(".")[-1])
	return choose_host_ip(
		network,
		excluded_hosts={device_host, gateway_host},
		preferred=DEFAULT_ADAPTER_HOST,
		fallbacks=(101, 102, 150, 200, 50, 75, 125),
	)


def choose_default_laptop_ip() -> str:
	network = DEFAULT_TEMPLATE_NETWORK
	return choose_host_ip(
		network,
		excluded_hosts={int(DEFAULT_DEVICE_IP.split(".")[-1]), DEFAULT_GATEWAY_HOST},
		preferred=DEFAULT_ADAPTER_HOST,
		fallbacks=(101, 102, 150, 200, 50, 75, 125),
	)


def set_adapter_ip(ip: str, mask: str, adapter: str = ADAPTER_NAME) -> bool:
	"""Set a static IP on the Windows Ethernet adapter using netsh."""
	if RDP_MODE:
		_arrow(f"[RDP] Skipping adapter change: {adapter} → {ip} / {mask}")
		return True

	print(f"  Setting {adapter} to {ip} / {mask} ...")
	cmd = f'netsh interface ip set address name="{adapter}" static {ip} {mask}'

	try:
		result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
		if result.returncode != 0:
			error_msg = result.stderr.strip() or result.stdout.strip()
			print(f"  ✗ Failed to set adapter IP: {error_msg}")
			return False

		_tick(f"Adapter set to {ip}")
		for remaining in range(NETWORK_SETTLE_TIME, -1, -1):
			print(f"\r  Waiting {remaining}s for adapter to settle...", end="", flush=True)
			if remaining:
				time.sleep(1)
		print()
		print()
		return True
	except subprocess.TimeoutExpired:
		print("  ✗ netsh command timed out.")
		return False
	except Exception as exc:
		print(f"  ✗ Error setting adapter: {exc}")
		return False


def read_template(path: Path) -> str:
	return path.read_bytes().decode("latin-1")


def rewrite_template(template_text: str, device: DeviceRecord) -> str:
	target_network = get_network(device.ip_address)
	gateway_ip = derive_gateway_ip(device)

	def replace_ip(match: re.Match[str]) -> str:
		value = match.group(0)
		try:
			parsed_ip = ipaddress.ip_address(value)
		except ValueError:
			return value

		if parsed_ip not in DEFAULT_TEMPLATE_NETWORK:
			return value

		host = int(value.split(".")[-1])
		if host == 254:
			return device.ip_address
		if host == DEFAULT_GATEWAY_HOST:
			return gateway_ip

		candidate_ip = ipaddress.ip_address(int(target_network.network_address) + host)
		if str(candidate_ip) in {device.ip_address, gateway_ip}:
			candidate_ip = ipaddress.ip_address(int(target_network.network_address) + ((host + 1) % 254 or 2))
		return str(candidate_ip)

	return re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", replace_ip, template_text)


def build_multipart_body(fields: dict[str, str], file_field_name: str, filename: str, file_bytes: bytes) -> tuple[bytes, str]:
	boundary = f"----MoxaUploadBoundary{int(time.time() * 1000)}"
	body_parts: list[bytes] = []

	for key, value in fields.items():
		body_parts.append(f"--{boundary}\r\n".encode())
		body_parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
		body_parts.append(value.encode("latin-1"))
		body_parts.append(b"\r\n")

	body_parts.append(f"--{boundary}\r\n".encode())
	body_parts.append(
		f'Content-Disposition: form-data; name="{file_field_name}"; filename="{filename}"\r\n'.encode()
	)
	body_parts.append(b"Content-Type: text/plain\r\n\r\n")
	body_parts.append(file_bytes)
	body_parts.append(b"\r\n")
	body_parts.append(f"--{boundary}--\r\n".encode())

	return b"".join(body_parts), boundary


def open_url(opener, url: str, method: str = "GET", data: Optional[bytes] = None, headers: Optional[dict[str, str]] = None) -> tuple[int, str, str]:
	request = Request(url, data=data, method=method)
	request.add_header("User-Agent", "Mozilla/5.0")
	if headers:
		for key, value in headers.items():
			request.add_header(key, value)

	try:
		with opener.open(request, timeout=30) as response:
			return response.getcode(), response.read().decode("latin-1", errors="replace"), response.geturl()
	except HTTPError as error:
		body = error.read().decode("latin-1", errors="replace") if error.fp else ""
		return error.code, body, url
	except URLError as error:
		raise MoxaUploadError(f"Request failed for {url}: {error.reason}") from error


def extract_token(page_text: str) -> Optional[str]:
	match = re.search(r'name=["\']token["\']\s+value=["\']([^"\']+)["\']', page_text, re.IGNORECASE)
	return match.group(1) if match else None


def extract_form_action(page_text: str) -> Optional[str]:
	match = re.search(
		r'<form[^>]*action=(?:["\']([^"\']+)["\']|([^\s>]+))',
		page_text,
		re.IGNORECASE,
	)
	if not match:
		return None
	return match.group(1) or match.group(2)


def extract_form_inputs(page_text: str) -> dict[str, str]:
	inputs: dict[str, str] = {}
	for name, value in re.findall(
		r'<input[^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']',
		page_text,
		re.IGNORECASE,
	):
		inputs[name] = value
	return inputs


def looks_like_password_prompt(page_text: str) -> bool:
	return bool(re.search(r"Input Password", page_text, re.IGNORECASE))


def submit_login(opener, base: str, page_url: str, page_text: str, password: str, debug_http: bool = False) -> bool:
	action = extract_form_action(page_text)
	login_url = urljoin(base, action or page_url)
	hidden_fields = extract_form_inputs(page_text)
	token_value = hidden_fields.get("Token") or hidden_fields.get("token")
	if not token_value:
		return False

	hashed_password = hashlib.md5((password + token_value).encode("latin-1")).hexdigest()
	fields = {"Token": token_value, "Password": hashed_password, "Submit": "Submit"}
	body = urlencode(fields).encode("utf-8")
	status, response_text, _ = open_url(
		opener,
		login_url,
		method="POST",
		data=body,
		headers={"Content-Type": "application/x-www-form-urlencoded"},
	)
	if debug_http:
		snippet = " ".join(response_text.split())[:400]
		print(f"  [debug] login POST status={status} url={login_url}")
		if snippet:
			print(f"  [debug] login response: {snippet}")
	return status < 400 and not looks_like_password_prompt(response_text)


def ensure_authenticated(opener, base: str, page_url: str, password: str, debug_http: bool = False) -> None:
	status, page_text, _ = open_url(opener, page_url, method="GET")
	if status >= 400:
		raise MoxaUploadError(f"Authentication probe failed for {page_url}: HTTP {status}")

	if looks_like_password_prompt(page_text):
		if not submit_login(opener, base, page_url, page_text, password, debug_http=debug_http):
			snippet = " ".join(page_text.split())[:400]
			if debug_http:
				print(f"  [debug] password prompt page: {snippet}")
			raise MoxaUploadError(f"Password prompt was shown but login failed for {page_url}")


def base_url(args: argparse.Namespace, ip_address: str) -> str:
	return f"{args.scheme}://{ip_address}/"


def upload_template(opener, base: str, args: argparse.Namespace, rendered_template: bytes, filename: str) -> None:
	upload_page_url = urljoin(base, args.upload_page)
	ensure_authenticated(opener, base, upload_page_url, args.password, debug_http=args.debug_http)
	status, page_text, _ = open_url(opener, upload_page_url, method="GET")
	if status >= 400:
		raise MoxaUploadError(f"Upload page request failed: HTTP {status}")
	if looks_like_password_prompt(page_text):
		raise MoxaUploadError("Upload page still shows a password prompt after login attempt")

	token = extract_token(page_text)
	if not token:
		raise MoxaUploadError("Upload page did not expose a token field")
	upload_target = urljoin(base, args.upload_action)
	_print_kv("Uploading to:", _host_from_base(upload_target))
	print()
	body, boundary = build_multipart_body(
		{"token": token, "NetConfig_OverWrite": "1", "import": "Import"},
		"importfile",
		filename,
		rendered_template,
	)
	size_kb = len(body) / 1024.0
	_print_kv("[API] Payload size:", f"{size_kb:.2f} KB")
	status, response_text, final_url = open_url(
		opener,
		upload_target,
		method="POST",
		data=body,
		headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
	)
	if status >= 400:
		raise MoxaUploadError(f"Upload failed with HTTP {status} from {final_url}")

	_print_kv("[API] Response status code:", str(status))
	print()
	_tick(f"Upload successful via {_host_from_base(upload_target)}!")
	_arrow("Config uploaded successfully. Preparing for restart...")


def restart_device(opener, base: str, args: argparse.Namespace) -> None:
	restart_page_url = urljoin(base, args.restart_page)
	_print_kv("Sending restart command to:", _host_from_base(base))
	print()
	ensure_authenticated(opener, base, restart_page_url, args.password, debug_http=args.debug_http)
	status, page_text, _ = open_url(opener, restart_page_url, method="GET")
	if status >= 400:
		raise MoxaUploadError(f"Restart page request failed: HTTP {status}")
	if looks_like_password_prompt(page_text):
		raise MoxaUploadError("Restart page still shows a password prompt after login attempt")

	token = extract_token(page_text)
	action = extract_form_action(page_text) or args.restart_action
	if token and action:
		query_string = urlencode({"token": token})
		separator = "&" if "?" in action else "?"
		restart_target = urljoin(base, f"{action}{separator}{query_string}")
		status, response_text, final_url = open_url(opener, restart_target, method="GET")
	else:
		fields = {"restart": "Restart"}
		if token:
			fields["token"] = token
		body, boundary = build_multipart_body(fields, "dummy", "restart.txt", b"")
		status, response_text, final_url = open_url(
			opener,
			urljoin(base, action),
			method="POST",
			data=body,
			headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
		)
	if status >= 400:
		raise MoxaUploadError(f"Restart POST failed with HTTP {status} from {final_url}")

	_print_kv("[API] Response status code:", str(status))
	print()
	_tick("Restart command sent (device restarting)")


def get_target_base_ip(args: argparse.Namespace, device: DeviceRecord) -> str:
	return device.ip_address if args.a2 else DEFAULT_DEVICE_IP


def wait_for_device(base: str, opener, timeout: int = POLL_TIMEOUT) -> bool:
	for path in ("01.htm", "status.html", ""):
		verify_url = urljoin(base, path)
		try:
			status, _, _ = open_url(opener, verify_url, method="GET")
			if status < 400:
				_tick(f"Device verified at {_host_from_base(base)} after restart")
				return True
		except MoxaUploadError:
			pass
	return False


def print_plan(device: DeviceRecord, template_path: Path, laptop_ip: str, gateway_ip: str, upload_mode: str) -> None:
	_print_header("MOXA CONFIG UPLOADER")
	_print_kv("Device:", device.device_name)
	_print_kv("Type:", device.device_type)
	_print_kv("IP Address:", device.ip_address)
	_print_kv("Gateway:", gateway_ip)
	_print_kv("Template:", template_path.name)
	_print_kv("Default IP:", DEFAULT_DEVICE_IP)
	print()
	_print_kv("Upload mode:", upload_mode)
	print()


def main() -> int:
	set_adapter_result = handle_set_adapter_command(sys.argv)
	if set_adapter_result is not None:
		return set_adapter_result

	args = parse_args()
	global RDP_MODE
	if args.rdp:
		RDP_MODE = True

	try:
		device = load_device_record(Path(args.device_list), args.device_name)
		template_path = load_template_path(Path(args.template_dir), args.template_file, device)
		raw_template = read_template(template_path)
		rewritten_template = rewrite_template(raw_template, device)
		rendered_bytes = rewritten_template.encode("latin-1")
		gateway_ip = derive_gateway_ip(device)
		initial_laptop_ip = choose_laptop_ip(device) if args.a2 else choose_default_laptop_ip()
		post_restart_laptop_ip = choose_laptop_ip(device)
		upload_mode = "device IP" if args.a2 else "default IP"

		print_plan(device, template_path, initial_laptop_ip, gateway_ip, upload_mode)

		if args.dry_run:
			print("Dry run requested; no network changes were made.")
			return 0

		if not args.skip_adapter_change:
			initial_ip = initial_laptop_ip
			if not set_adapter_ip(initial_ip, DEFAULT_SUBNET_MASK, adapter=args.adapter_name):
				return 1

		cookie_jar = CookieJar()
		opener = build_opener(HTTPCookieProcessor(cookie_jar))
		target_base_ip = get_target_base_ip(args, device)
		target_base = base_url(args, target_base_ip)

		upload_template(opener, target_base, args, rendered_bytes, template_path.name)

		restart_device(opener, target_base, args)

		if not args.skip_adapter_change:
			if not set_adapter_ip(post_restart_laptop_ip, DEFAULT_SUBNET_MASK, adapter=args.adapter_name):
				return 1

		for remaining in range(POST_RESTART_WAIT, -1, -1):
			print(f"\r  Waiting {remaining}s for the device to reboot...", end="", flush=True)
			time.sleep(1)
		print()
		print()

		verify_base = base_url(args, device.ip_address)
		_print_kv("Verifying:", _host_from_base(verify_base))
		if wait_for_device(verify_base, opener):
			if not args.skip_adapter_change:
				_tick(f"Adapter is now configured for: {post_restart_laptop_ip}")
			_tick(f"Done! '{device.device_name}' configured successfully.")
			return 0

		print("Device did not respond on the expected IP before timeout.")
		return 2

	except MoxaUploadError as exc:
		print(f"Error: {exc}")
		return 1
	except KeyboardInterrupt:
		print("Interrupted.")
		return 130


if __name__ == "__main__":
	raise SystemExit(main())
