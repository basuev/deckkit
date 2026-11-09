"""Use the local Steam client without a resident injection framework."""

import base64
import hashlib
import json
import os
import socket
import struct
import time
import urllib.request


class SteamClient:
    """Synchronous CDP client for the local Steam debug endpoint."""

    def __init__(self, endpoint="http://127.0.0.1:8080"):
        from urllib.parse import urlsplit

        url = urlsplit(endpoint)
        if url.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("The Steam endpoint must be local.")
        self.endpoint = endpoint.rstrip("/")

    def __enter__(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(self.endpoint + "/json/list", timeout=4) as response:
            pages = json.load(response)
        page = next(p for p in pages if p["title"] == "SharedJSContext")
        from urllib.parse import urlsplit

        url = urlsplit(page["webSocketDebuggerUrl"])
        self.sock = socket.create_connection(
            ("127.0.0.1", url.port), timeout=5
        )
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {url.path} HTTP/1.1\r\nHost: 127.0.0.1:{url.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        headers = b""
        try:
            while not headers.endswith(b"\r\n\r\n"):
                headers += self.read(1)
                if len(headers) > 16384:
                    raise RuntimeError("Invalid Steam client response.")
        except Exception:
            self.sock.close()
            raise
        accept = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()
        )
        if (
            not headers.startswith(b"HTTP/1.1 101")
            or accept.lower() not in headers.lower()
        ):
            self.sock.close()
            raise RuntimeError("Steam client connection failed.")
        self.sequence = 0
        return self

    def __exit__(self, *_):
        self.sock.close()

    def read(self, count):
        data = b""
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise RuntimeError("Steam client disconnected.")
            data += chunk
        return data

    def send(self, data, opcode=1):
        mask = os.urandom(4)
        size = len(data)
        header = bytes([0x80 | opcode, 0x80 | (size if size < 126 else 126)])
        if size >= 126:
            header += struct.pack("!H", size)
        self.sock.sendall(
            header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        )

    def evaluate(self, expression):
        self.sequence += 1
        self.send(
            json.dumps(
                {
                    "id": self.sequence,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expression,
                        "returnByValue": True,
                        "awaitPromise": True,
                    },
                }
            ).encode()
        )
        message = b""
        while True:
            first, second = self.read(2)
            size = second & 127
            if size == 126:
                size = struct.unpack("!H", self.read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.read(8))[0]
            mask = self.read(4) if second & 128 else None
            payload = self.read(size)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            opcode = first & 15
            if opcode == 8:
                raise RuntimeError("Steam client closed the connection.")
            if opcode == 9:
                self.send(payload, 10)
                continue
            if opcode not in (0, 1):
                continue
            message += payload
            if not first & 128:
                continue
            response = json.loads(message)
            message = b""
            if response.get("id") != self.sequence:
                continue
            result = response.get("result", {})
            if "error" in response or "exceptionDetails" in result:
                raise RuntimeError("Steam could not apply the launch profile.")
            return result.get("result", {}).get("value")


def varint(value):
    out = bytearray()
    while value > 127:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def message(fields):
    out = b""
    for number, value in fields.items():
        out += varint(number * 8) + varint(int(value))
    return out


def display_settings():
    # The current QAM uses this adapter rather than the legacy Perf API.
    # Both FPS choices retain stock 15 W and use only the game's FPS limiter.
    return {
        "gamescope_app_target_framerate": 90,
        "gamescope_enable_app_target_framerate": True,
        "gamescope_disable_framelimit": True,
        "gamescope_display_refresh_rate": 90,
        "gamescope_allow_tearing": True,
        "steamos_tdp_limit_enabled": False,
    }


FIELDS = {
    "gamescope_app_target_framerate": 21002,
    "gamescope_enable_app_target_framerate": 21003,
    "gamescope_disable_framelimit": 21004,
    "gamescope_display_refresh_rate": 21005,
    "gamescope_allow_tearing": 21009,
    "steamos_tdp_limit_enabled": 22001,
    "steamos_tdp_limit": 22002,
}


def decode_fields(data):
    data = bytes(data)
    pos = 0

    def read_varint():
        nonlocal pos
        value = shift = 0
        while pos < len(data) and shift < 70:
            byte = data[pos]
            pos += 1
            value |= (byte & 127) << shift
            if not byte & 128:
                return value
            shift += 7
        raise ValueError("Invalid Steam protobuf value")

    result = {}
    while pos < len(data):
        tag = read_varint()
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value = read_varint()
        elif wire == 2:
            size = read_varint()
            value = data[pos : pos + size]
            pos += size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value = data[pos : pos + size]
            pos += size
        else:
            raise ValueError("Unsupported Steam protobuf field")
        if pos > len(data):
            raise ValueError("Truncated Steam protobuf field")
        result[field] = value
    return result


def subscription(client, expression):
    return client.evaluate(
        """new Promise((resolve,reject)=>{
      let subscription;
      const timer=setTimeout(()=>{
        subscription?.unregister();
        reject(new Error("Steam state timed out"));
      },2500);
      subscription="""
        + expression
        + """(value=>{
        clearTimeout(timer);
        resolve(Array.from(new Uint8Array(value)));
        queueMicrotask(()=>subscription?.unregister());
      });
    })"""
    )


class SteamAPI:
    def __init__(self, endpoint="http://127.0.0.1:8080"):
        self.endpoint = endpoint

    def available(self):
        try:
            with SteamClient(self.endpoint) as client:
                return (
                    client.evaluate(
                        'typeof SteamClient.Settings.SetSetting === "function"'
                    )
                    is True
                )
        except (OSError, RuntimeError, ValueError, StopIteration):
            return False

    def active_game(self):
        with SteamClient(self.endpoint) as client:
            raw = subscription(
                client, "SteamClient.System.Perf.RegisterForStateChanges"
            )
        return str(decode_fields(raw).get(3, 0))

    def wait_for_game(self, pump=lambda: None):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            pump()
            if self.active_game() == "1091500":
                return
            time.sleep(0.1)
        raise RuntimeError(
            "Steam has not activated the Cyberpunk profile. Try Play again."
        )

    def snapshot(self):
        with SteamClient(self.endpoint) as client:
            raw = subscription(
                client, "SteamClient.Settings.RegisterForSettingsArrayChanges"
            )
        decoded = decode_fields(raw)
        return {
            name: decoded[number]
            for name, number in FIELDS.items()
            if number in decoded
        }

    def set_settings(self, values):
        payload = base64.b64encode(
            message({FIELDS[k]: v for k, v in values.items()})
        ).decode()
        with SteamClient(self.endpoint) as client:
            result = client.evaluate(
                "SteamClient.Settings.SetSetting(" + json.dumps(payload) + ")"
            )
        if result is not True:
            raise RuntimeError("Steam did not apply the selected settings.")

    def apply_display_settings(self):
        values = display_settings()
        self.set_settings(values)
        return values

    def set_launch_options(self, value):
        with SteamClient(self.endpoint) as client:
            client.evaluate(
                "SteamClient.Apps.SetAppLaunchOptions(1091500,"
                + json.dumps(value or "")
                + ")"
            )
