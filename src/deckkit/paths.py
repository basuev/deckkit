"""User-owned installation paths and the external-process environment."""

import json
import os
import sys
import tempfile
from pathlib import Path


def external_environment():
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = original
        for key in ("TCL_LIBRARY", "TK_LIBRARY", "PYTHONHOME", "PYTHONPATH"):
            env.pop(key, None)
        for key in list(env):
            if key.startswith("_PYI_"):
                env.pop(key)
    return env


def write_atomic(path, content, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".deckkit-", delete=False
        ) as out:
            temp = Path(out.name)
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        temp.chmod(mode)
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def write_json(path, data):
    write_atomic(path, (json.dumps(data, indent=2) + "\n").encode())


class Paths:
    def __init__(self, home=None):
        self.home = Path(home) if home else Path.home()
        self.data = self.home / ".local/share/deckkit"
        self.state = self.home / ".local/state/deckkit"
        self.packages = self.data / "packages"
        self.runtime = self.data / "runtime"
        self.command = self.data / "deckkit"
        self.config = self.home / ".config/deckkit/config.json"
        self.applications = self.home / ".local/share/applications"

    def receipt(self, package_id):
        return self.state / "packages" / package_id / "receipt.json"


def bundle_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def data_root(bundle=None):
    root = Path(bundle) if bundle else bundle_root()
    frozen = root / "_internal/data"
    return frozen if frozen.is_dir() else root / "assets"
