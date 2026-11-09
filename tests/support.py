import json
import os
import shutil
from pathlib import Path

from deckkit import steam
from deckkit.input import Gamepads
from deckkit.install import Installer
from deckkit.paths import Paths

ROOT = Path(__file__).resolve().parents[1]


class FakeSteamAPI:
    def __init__(self, root, account):
        self.root, self.account = root, account
        self.values = {
            "gamescope_app_target_framerate": 45,
            "gamescope_enable_app_target_framerate": 1,
            "gamescope_disable_framelimit": 0,
            "gamescope_display_refresh_rate": 45,
            "gamescope_allow_tearing": 0,
            "steamos_tdp_limit_enabled": 0,
            "steamos_tdp_limit": 15,
        }
        self.calls = []

    def available(self):
        return True

    def set_launch_options(self, value):
        self.calls.append(value)
        steam.write_launch_options(self.root, self.account, value)

    def wait_for_game(self, pump=lambda: None):
        pump()

    def snapshot(self):
        return self.values.copy()

    def set_settings(self, values):
        self.values.update(values)

    def apply_display_settings(self):
        from deckkit.steam_api import display_settings

        values = display_settings()
        self.set_settings(values)
        return values


def fixture(base, sd=False):
    home = base / "home with spaces"
    paths = Paths(home)
    root = home / ".local/share/Steam"
    (root / "steamapps").mkdir(parents=True)
    library = base / "SD card" if sd else root
    (library / "steamapps/common/Cyberpunk 2077/bin/x64").mkdir(parents=True)
    game = library / "steamapps/common/Cyberpunk 2077"
    (game / "bin/x64/Cyberpunk2077.exe").write_bytes(b"fixture")
    (library / "steamapps/appmanifest_1091500.acf").write_text(
        '"AppState" { "installdir" "Cyberpunk 2077" }'
    )
    if sd:
        (root / "steamapps/libraryfolders.vdf").write_text(
            '"libraryfolders" { "1" { "path" '
            + json.dumps(str(library))
            + " } }"
        )
    user = root / "steamapps/compatdata/1091500/pfx/drive_c/users/steamuser"
    settings = (
        user / "AppData/Local/CD Projekt Red/Cyberpunk 2077/UserSettings.json"
    )
    settings.parent.mkdir(parents=True)
    data = {
        "data": [
            {
                "group_name": "/video/display",
                "options": [
                    {"name": "MaximumFPS_OnOff", "value": False},
                    {"name": "MaximumFPS_Value", "value": 30},
                    {
                        "name": "VSync",
                        "value": "UI-Settings-Video-QualitySetting-Off",
                        "index": 0,
                    },
                    {"name": "Resolution", "value": "1280x800", "index": 1},
                    {"name": "WindowMode", "value": "Fullscreen", "index": 0},
                ],
            },
            {
                "group_name": "/graphics",
                "options": [
                    {
                        "name": "TextureQuality",
                        "value": "High",
                        "index": 2,
                        "values": ["Low", "Medium", "High"],
                    }
                ],
            },
            {
                "group_name": "/accessibility",
                "options": [{"name": "TextSize", "value": 62}],
            },
        ],
        "user_metadata": "preserve",
    }
    settings.write_text(json.dumps(data, indent=2))
    saves = user / "Saved Games/CD Projekt Red/Cyberpunk 2077"
    saves.mkdir(parents=True)
    (saves / "campaign.dat").write_bytes(b"never touch this save")
    account = "123"
    cfg = root / f"userdata/{account}/config/localconfig.vdf"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        '"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { '
        '"apps" { "1091500" { "LaunchOptions" '
        '"FOO=bar %command% --existing" } } } } } }'
    )
    (root / "config").mkdir()
    (root / "config/loginusers.vdf").write_text(
        '"users" { "76561197960265851" { "MostRecent" "1" } }'
    )
    bundle = base / "bundle"
    bundle.mkdir()
    binary = bundle / "deckkit"
    binary.write_text(
        '#!/bin/sh\nif [ "$1" = "--version" ]; then echo 0.1.0; fi\n'
    )
    binary.chmod(0o755)
    shutil.copytree(ROOT / "assets", bundle / "assets")
    steam_api = FakeSteamAPI(root, account)
    installer = Installer(paths, steam_api=steam_api, bundle=bundle)
    return {
        "installer": installer,
        "paths": paths,
        "root": root,
        "game": game,
        "settings": settings,
        "saves": saves,
        "data": data,
        "bundle": bundle,
        "steam_api": steam_api,
        "account": account,
    }


class PipePad(Gamepads):
    """Feed Linux controller events through the real input decoder."""

    def __init__(self, root, navigate, confirm, cancel):
        self.root = root
        self.navigate, self.confirm, self.cancel = navigate, confirm, cancel
        self.closed = False
        self.fd, self.writer = os.pipe2(os.O_NONBLOCK)
        self.devices = {
            self.fd: {
                "path": "test controller",
                "buffer": b"",
                "axes": {0: (-32768, 32767)},
                "directions": {},
            }
        }
        root.createfilehandler(self.fd, 2, self.read)
        self.timer = root.after(999999, lambda: None)

    def send(self, kind, code, value):
        os.write(self.writer, self.EVENT.pack(0, 0, kind, code, value))
        self.root.update()

    def move(self, dx=0, dy=0):
        code, value = (16, dx) if dx else (17, dy)
        self.send(3, code, value)
        self.send(3, code, 0)

    def accept(self):
        self.send(1, 304, 1)
        if not self.closed:
            self.send(1, 304, 0)

    def close(self):
        super().close()
        os.close(self.writer)
