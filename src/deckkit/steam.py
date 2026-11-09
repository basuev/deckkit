"""Discover Steam libraries and preserve user integration settings."""

import configparser
import os
import shlex
import subprocess
import time
import zlib
from pathlib import Path

from . import vdf
from .paths import external_environment, write_atomic

APPID = "1091500"
APP_PATH = [
    "UserLocalConfigStore",
    "Software",
    "Valve",
    "Steam",
    "apps",
    APPID,
    "LaunchOptions",
]


def steam_root(home):
    for path in (
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".steam/root",
    ):
        if (path / "steamapps").is_dir():
            return path.resolve()
    raise RuntimeError("Steam was not found.")


def libraries(root):
    result = [root]
    config = root / "steamapps/libraryfolders.vdf"
    if config.exists():
        obj = vdf.lookup(config.read_text(), ["libraryfolders"])
        for node in (obj or {}).get("children", []):
            entry = vdf.child(node.get("children", []), "path")
            value = entry.get("value") if entry else node.get("value")
            if value and Path(value).is_dir() and Path(value) not in result:
                result.append(Path(value))
    return result


def find_game(root):
    libs = libraries(root)
    for library in libs:
        manifest = library / f"steamapps/appmanifest_{APPID}.acf"
        if not manifest.exists():
            continue
        node = vdf.lookup(manifest.read_text(), ["AppState", "installdir"])
        if node:
            game = library / "steamapps/common" / node["value"]
            if (game / "bin/x64/Cyberpunk2077.exe").exists():
                return game
    raise RuntimeError(
        "Install Cyberpunk 2077 in Steam, then open this installer again."
    )


def find_settings(root, game):
    # Compatdata can live in a different library from the game itself.
    for library in [game.parents[2], *libraries(root)]:
        path = (
            library
            / f"steamapps/compatdata/{APPID}/pfx/drive_c/users/steamuser"
            / "AppData/Local/CD Projekt Red/Cyberpunk 2077/UserSettings.json"
        )
        if path.exists():
            return path
    raise RuntimeError(
        "Start Cyberpunk once and exit from its main menu, "
        "then install this package."
    )


def active_account(root):
    users = root / "config/loginusers.vdf"
    if users.exists():
        obj = vdf.lookup(users.read_text(), ["users"])
        candidates = (obj or {}).get("children", [])
        for node in sorted(
            candidates,
            key=lambda n: (
                vdf.child(n.get("children", []), "MostRecent") or {}
            ).get("value", "0"),
            reverse=True,
        ):
            try:
                account = str(int(node["key"]) & 0xFFFFFFFF)
            except ValueError:
                continue
            if (root / "userdata" / account).is_dir():
                return account
    accounts = [
        p.name
        for p in (root / "userdata").glob("*")
        if p.name.isdigit() and p.name != "0"
    ]
    if len(accounts) == 1:
        return accounts[0]
    raise RuntimeError("Sign in to Steam before installing deckkit.")


def local_config(root, account):
    return root / "userdata" / account / "config/localconfig.vdf"


def launch_options(root, account):
    config = local_config(root, account)
    text = (
        config.read_text()
        if config.exists()
        else '"UserLocalConfigStore"\n{\n}\n'
    )
    node = vdf.lookup(text, APP_PATH)
    return node["value"] if node else None


def write_launch_options(root, account, value):
    config = local_config(root, account)
    text = (
        config.read_text()
        if config.exists()
        else '"UserLocalConfigStore"\n{\n}\n'
    )
    write_atomic(config, vdf.set_value(text, APP_PATH, value).encode())


def strip_legacy_launcher(original):
    original = original if original is not None else "%command%"
    # Adopt the earlier personal selector without nesting two launchers.
    legacy = (
        str(Path.home() / ".local/share/codex-deck-ui/launcher.py") + " -- "
    )
    return original.replace(legacy, "")


def wrap_options(original, command):
    original = strip_legacy_launcher(original)
    if original.count("%command%") != 1:
        raise RuntimeError(
            "Steam launch options need exactly one %command% placeholder."
        )
    return original.replace("%command%", command + " -- %command%")


def unwrap_options(current, receipt):
    if current == receipt["after"]:
        return receipt["before"]
    return (
        current.replace(receipt["wrapper"] + " -- %command%", "%command%", 1)
        if current
        else current
    )


def processes():
    uid = os.getuid()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != uid:
                continue
            args = (proc / "cmdline").read_bytes().split(b"\0")
            if args and args[0]:
                yield proc, args
        except OSError:
            pass


def game_running():
    return any(
        args[0].lower().endswith(b"cyberpunk2077.exe")
        for _, args in processes()
    )


def steam_running():
    return any(
        Path(os.fsdecode(args[0])).name == "steam" for _, args in processes()
    )


def close_steam():
    if game_running():
        raise RuntimeError("Close Cyberpunk before changing its installation.")
    if not steam_running():
        return False
    # Called only by the Desktop installer, after its explicit restart action.
    subprocess.run(
        ["steam", "-shutdown"],
        env=external_environment(),
        capture_output=True,
        timeout=20,
        check=True,
    )
    deadline = time.monotonic() + 30
    while steam_running() and time.monotonic() < deadline:
        time.sleep(0.2)
    if steam_running():
        raise RuntimeError("Close Steam to finish configuring this package.")
    return True


def shortcut_file(root, account):
    return root / "userdata" / account / "config/shortcuts.vdf"


def shortcut_appid(command, name="deckkit"):
    return zlib.crc32((f'"{command}"' + name).encode()) | 0x80000000


def register_shortcut(root, account, command, icon):
    path = shortcut_file(root, account)
    nodes = (
        vdf.decode_binary(path.read_bytes())
        if path.exists()
        else [[0, "shortcuts", []]]
    )
    shortcuts = next(n[2] for n in nodes if n[0] == 0 and n[1] == "shortcuts")
    package_id = shortcut_appid(command)
    for item in shortcuts:
        if any(
            n[1] == "appid" and n[2] == vdf.integer(package_id)
            for n in item[2]
        ):
            return package_id
    fields = [
        [2, "appid", vdf.integer(package_id)],
        [1, "AppName", "deckkit"],
        [1, "Exe", f'"{command}"'],
        [1, "StartDir", f'"{command.parent}"'],
        [1, "icon", str(icon)],
        [1, "ShortcutPath", ""],
        [1, "LaunchOptions", "catalog"],
        [2, "IsHidden", vdf.integer(0)],
        [2, "AllowDesktopConfig", vdf.integer(1)],
        [2, "AllowOverlay", vdf.integer(1)],
        [2, "OpenVR", vdf.integer(0)],
        [2, "Devkit", vdf.integer(0)],
        [1, "DevkitGameID", ""],
        [2, "LastPlayTime", vdf.integer(0)],
        [0, "tags", []],
    ]
    used = {n[1] for n in shortcuts}
    index = next(str(n) for n in range(len(used) + 1) if str(n) not in used)
    shortcuts.append([0, index, fields])
    write_atomic(path, vdf.encode_binary(nodes))
    return package_id


def command_string(command, *args):
    return shlex.join([str(command), *args])


def return_to_gaming(home):
    # Use Valve's installed entry to select the Gaming Mode session.
    for directory in (home / "Desktop", Path("/usr/share/applications")):
        for path in directory.glob("*.desktop"):
            parser = configparser.ConfigParser(interpolation=None)
            try:
                parser.read(path)
                name = parser["Desktop Entry"].get("Name", "")
                command = parser["Desktop Entry"].get("Exec", "")
                if "return" in name.lower() and "gaming" in name.lower():
                    subprocess.Popen(
                        shlex.split(command), env=external_environment()
                    )
                    return
            except (OSError, ValueError, KeyError):
                continue
    raise RuntimeError("Use SteamOS's Return to Gaming Mode desktop shortcut.")
