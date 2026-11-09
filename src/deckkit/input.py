"""Read gamepads without grabbing or synthesizing input."""

import fcntl
import os
import struct
from pathlib import Path


def has_bit(value, bit):
    words = value.split()
    bits = struct.calcsize("L") * 8
    return any(
        int(word, 16) & (1 << (bit - index * bits))
        for index, word in enumerate(reversed(words))
        if index * bits <= bit < (index + 1) * bits
    )


class Gamepads:
    EVENT = struct.Struct("llHHi")

    def __init__(self, root, navigate, confirm, cancel):
        self.root, self.navigate, self.confirm, self.cancel = (
            root,
            navigate,
            confirm,
            cancel,
        )
        self.devices = {}
        self.closed = False
        self.scan()

    def scan(self):
        if self.closed:
            return
        opened = {item["path"] for item in self.devices.values()}
        for device in Path("/sys/class/input").glob("event*/device"):
            try:
                keys = (device / "capabilities/key").read_text().strip()
                # BTN_GAMEPAD works across virtual controller names.
                if not has_bit(keys, 0x130):
                    continue
                path = "/dev/input/" + device.parent.name
                if path in opened:
                    continue
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                axes = {}
                for code in (0, 1, 3, 4):
                    try:
                        info = bytearray(24)
                        fcntl.ioctl(fd, 0x80184540 + code, info)
                        _, low, high, _, _, _ = struct.unpack("6i", info)
                        if high > low:
                            axes[code] = (low, high)
                    except OSError:
                        pass
                self.devices[fd] = {
                    "path": path,
                    "buffer": b"",
                    "axes": axes,
                    "directions": {},
                }
                self.root.createfilehandler(fd, 2, self.read)
            except (OSError, ValueError):
                continue
        self.timer = self.root.after(1500, self.scan)

    def read(self, fd, _):
        try:
            data = os.read(fd, self.EVENT.size * 64)
            if not data:
                self.remove(fd)
                return
            item = self.devices[fd]
            item["buffer"] += data
            while len(item["buffer"]) >= self.EVENT.size and not self.closed:
                _, _, kind, code, value = self.EVENT.unpack(
                    item["buffer"][: self.EVENT.size]
                )
                item["buffer"] = item["buffer"][self.EVENT.size :]
                if not self.root.focus_displayof():
                    continue
                if kind == 3 and code in (16, 17) and value:
                    self.navigate(
                        value if code == 16 else 0, value if code == 17 else 0
                    )
                elif kind == 3 and code in item["axes"]:
                    low, high = item["axes"][code]
                    position = (value - (low + high) / 2) / ((high - low) / 2)
                    previous = item["directions"].get(code, 0)
                    direction = (
                        1 if position > 0.55 else -1 if position < -0.55 else 0
                    )
                    if abs(position) < 0.35:
                        item["directions"][code] = 0
                    elif direction and direction != previous:
                        item["directions"][code] = direction
                        self.navigate(
                            direction if code in (0, 3) else 0,
                            direction if code in (1, 4) else 0,
                        )
                elif kind == 1 and value == 1:
                    if code == 304:
                        self.confirm()
                    elif code == 305:
                        self.cancel()
                    elif code in (544, 545, 546, 547):
                        self.navigate(
                            -1 if code == 546 else 1 if code == 547 else 0,
                            -1 if code == 544 else 1 if code == 545 else 0,
                        )
        except BlockingIOError:
            pass
        except OSError:
            self.remove(fd)

    def remove(self, fd):
        if fd in self.devices:
            self.root.deletefilehandler(fd)
            os.close(fd)
            del self.devices[fd]

    def close(self):
        self.closed = True
        self.root.after_cancel(self.timer)
        for fd in list(self.devices):
            self.remove(fd)
