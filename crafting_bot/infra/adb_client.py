from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image


class AdbClient:
    """
    Small ADB adapter. It captures screenshots and taps coordinates.

    It also owns ADB connection recovery because callers should not need to know
    whether BlueStacks is currently exposed on 5555, 5556, or another local port.
    """

    DEFAULT_CONNECT_PORTS = (5555, 5556, 5565, 5575, 5585)
    DEFAULT_BLUESTACKS_CONF = Path(r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf")

    def __init__(
        self,
        adb_path: str | Path | None = None,
        timeout_seconds: float = 15.0,
        device_serial: str | None = None,
        auto_connect: bool = True,
        bluestacks_conf_path: str | Path | None = None,
    ) -> None:
        self.adb_path = str(adb_path) if adb_path else self._find_adb()
        self.timeout_seconds = timeout_seconds
        self.device_serial = device_serial
        self.auto_connect = auto_connect
        self.bluestacks_conf_path = (
            Path(bluestacks_conf_path)
            if bluestacks_conf_path is not None
            else self.DEFAULT_BLUESTACKS_CONF
        )
        self.last_connection_message = ""

    def capture(self) -> Image.Image:
        self.ensure_device()
        completed = self._run_device(["exec-out", "screencap", "-p"], capture_output=True)
        if completed.stdout is None:
            raise RuntimeError("ADB screencap returned no image data.")

        from io import BytesIO

        return Image.open(BytesIO(completed.stdout)).convert("RGB")

    def capture_to_file(self, path: Path) -> Image.Image:
        image = self.capture()
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        return image

    def tap(self, x: int, y: int) -> None:
        self.ensure_device()
        self._run_device(["shell", "input", "tap", str(int(x)), str(int(y))], capture_output=True)

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 750) -> None:
        """Send an ADB swipe gesture.

        For this bot, a swipe is used as a click-and-hold drag: press at the
        calibrated start point, move to the calibrated end point, then release.
        """
        self.ensure_device()
        self._run_device(
            [
                "shell",
                "input",
                "swipe",
                str(int(start_x)),
                str(int(start_y)),
                str(int(end_x)),
                str(int(end_y)),
                str(max(1, int(duration_ms))),
            ],
            capture_output=True,
        )

    def keyevent(self, key: str | int) -> None:
        """Send an Android keyevent through ADB.

        The recovery system uses this for ESC/BACK-style recovery. For Android,
        KEYCODE_BACK is the safest equivalent to pressing ESC in BlueStacks for
        returning from most menus.
        """
        self.ensure_device()
        self._run_device(["shell", "input", "keyevent", str(key)], capture_output=True)

    def press_back(self) -> None:
        """Press Android Back once.

        BlueStacks maps the physical ESC key to the same general behavior for
        the game, but using ADB KEYCODE_BACK avoids keyboard focus issues.
        """
        self.keyevent("KEYCODE_BACK")

    def ensure_device(self) -> str:
        """Return a connected ADB device serial, trying BlueStacks auto-connect if needed."""
        devices = self.list_devices()
        preferred = self._pick_device(devices)
        if preferred:
            self.device_serial = preferred
            self.last_connection_message = f"ADB device already connected: {preferred}"
            return preferred

        if not self.auto_connect:
            raise RuntimeError("No ADB devices connected, and auto-connect is disabled.")

        tried: list[str] = []
        for address in self._candidate_addresses():
            tried.append(address)
            try:
                self.connect(address)
            except RuntimeError:
                continue

            devices = self.list_devices()
            preferred = self._pick_device(devices)
            if preferred:
                self.device_serial = preferred
                self.last_connection_message = f"ADB auto-connected to {preferred}"
                return preferred

        tried_text = ", ".join(tried) if tried else "no ports found"
        raise RuntimeError(
            "No ADB device connected. "
            f"Tried BlueStacks addresses: {tried_text}. "
            "Open BlueStacks, enable ADB, then run the scan again."
        )

    def list_devices(self) -> list[tuple[str, str]]:
        completed = self._run_raw(["devices"], capture_output=True)
        stdout = completed.stdout.decode("utf-8", errors="replace") if completed.stdout else ""

        devices: list[tuple[str, str]] = []
        for raw_line in stdout.splitlines()[1:]:
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices.append((parts[0], parts[1]))

        return devices

    def connect(self, address: str) -> str:
        completed = self._run_raw(["connect", address], capture_output=True)
        stdout = completed.stdout.decode("utf-8", errors="replace") if completed.stdout else ""
        stderr = completed.stderr.decode("utf-8", errors="replace") if completed.stderr else ""
        message = (stdout + stderr).strip()

        if "unable to connect" in message.lower() or "cannot connect" in message.lower():
            raise RuntimeError(message or f"Unable to connect to {address}")

        return message

    def _pick_device(self, devices: list[tuple[str, str]]) -> str | None:
        if self.device_serial:
            for serial, state in devices:
                if serial == self.device_serial and state == "device":
                    return serial

        for serial, state in devices:
            if state == "device":
                return serial

        return None

    def _candidate_addresses(self) -> list[str]:
        ports: list[int] = []

        # BlueStacks can keep a stale/default adb_port and a separate live
        # status.adb_port. Prefer the live status value when it exists.
        status_ports, configured_ports = self._read_bluestacks_ports()
        ports.extend(status_ports)
        ports.extend(configured_ports)
        ports.extend(self.DEFAULT_CONNECT_PORTS)

        addresses: list[str] = []
        seen_ports: set[int] = set()
        for port in ports:
            if port in seen_ports:
                continue
            seen_ports.add(port)
            addresses.append(f"127.0.0.1:{port}")

        return addresses

    def _read_bluestacks_ports(self) -> tuple[list[int], list[int]]:
        if not self.bluestacks_conf_path.exists():
            return [], []

        try:
            text = self.bluestacks_conf_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return [], []

        status_ports: list[int] = []
        configured_ports: list[int] = []

        for line in text.splitlines():
            stripped = line.strip()

            status_match = re.search(r"\.status\.adb_port\s*=\s*\"?(\d+)\"?", stripped)
            if status_match:
                status_ports.append(int(status_match.group(1)))
                continue

            configured_match = re.search(r"\.adb_port\s*=\s*\"?(\d+)\"?", stripped)
            if configured_match:
                configured_ports.append(int(configured_match.group(1)))

        return self._unique(status_ports), self._unique(configured_ports)

    @staticmethod
    def _unique(values: list[int]) -> list[int]:
        result: list[int] = []
        seen: set[int] = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _run_device(self, args: list[str], capture_output: bool) -> subprocess.CompletedProcess[bytes]:
        if self.device_serial:
            return self._run_raw(["-s", self.device_serial, *args], capture_output=capture_output)
        return self._run_raw(args, capture_output=capture_output)

    def _run_raw(self, args: list[str], capture_output: bool) -> subprocess.CompletedProcess[bytes]:
        cmd = [self.adb_path, *args]

        # When the bot is launched through pythonw.exe / .vbs, Windows console
        # executables such as HD-Adb.exe can still create their own temporary
        # console windows unless subprocess is explicitly told not to.
        run_kwargs: dict[str, object] = {}
        if os.name == "nt":
            run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            run_kwargs["startupinfo"] = startupinfo

        try:
            completed = subprocess.run(
                cmd,
                check=False,
                capture_output=capture_output,
                timeout=self.timeout_seconds,
                stdin=subprocess.DEVNULL,
                **run_kwargs,
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"ADB executable was not found: {self.adb_path}. "
                "Set the correct adb_path before running the bot."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"ADB command timed out: {' '.join(cmd)}") from exc

        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace") if completed.stderr else ""
            stdout = completed.stdout.decode("utf-8", errors="replace") if completed.stdout else ""
            details = (stderr or stdout).strip()
            raise RuntimeError(f"ADB command failed: {' '.join(cmd)}\n{details}")

        return completed

    @staticmethod
    def _find_adb() -> str:
        found = shutil.which("adb")
        if found:
            return found

        bluestacks = Path(r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe")
        if bluestacks.exists():
            return str(bluestacks)

        return "adb"
