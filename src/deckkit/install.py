"""Package lifecycle shared by the installer, catalog and command line."""

import contextlib
import copy
import fcntl
import json
import os
import shutil
import tempfile
from pathlib import Path

from . import catalog, cyberpunk, runtime, steam
from .archive import download, extract
from .journal import Journal
from .paths import (
    Paths,
    bundle_root,
    data_root,
    write_atomic,
    write_json,
)
from .steam_api import SteamAPI


class Installer:
    def __init__(self, paths=None, steam_api=None, bundle=None):
        self.paths = paths or Paths()
        self.bundle = Path(bundle) if bundle else bundle_root()
        self.data = data_root(self.bundle)
        config = (
            json.loads(self.paths.config.read_text())
            if self.paths.config.exists()
            else {}
        )
        self.steam_api = steam_api or SteamAPI(
            config.get("steam_endpoint", "http://127.0.0.1:8080")
        )
        self.catalog, self.catalog_url = catalog.load(
            self.data, self.paths.state, config
        )

    @contextlib.contextmanager
    def lock(self):
        self.paths.state.mkdir(parents=True, exist_ok=True)
        with (self.paths.state / "operation.lock").open("w") as fd:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another deckkit operation is in progress.")
            yield

    def load_receipt(self, package_id):
        path = self.paths.receipt(package_id)
        if not path.exists():
            return None
        receipt = json.loads(path.read_text())
        receipt["receipt_path"] = str(path)
        return receipt

    def save_receipt(self, receipt):
        write_json(self.paths.receipt(receipt["id"]), receipt)

    def packages(self):
        return self.catalog["packages"]

    def entry(self, package_id):
        return next(p for p in self.packages() if p["id"] == package_id)

    def refresh(self):
        self.catalog = catalog.fetch(self.catalog_url, self.paths.state)

    def update_runtime(self, progress=lambda text: None):
        with self.lock():
            runtime.update(self.paths, self.catalog.get("runtime"), progress)

    def package_source(self, entry, temp, progress):
        builtin = self.data / "packages" / entry["id"]
        if (
            builtin.exists()
            and json.loads((builtin / "package.json").read_text())["version"]
            == entry["version"]
        ):
            shutil.copytree(builtin, temp / "package")
        else:
            progress("Downloading " + entry["name"])
            download(
                entry["asset"]["url"],
                temp / "package.tar.gz",
                entry["asset"]["sha256"],
            )
            extract(temp / "package.tar.gz", temp / "package")
        manifest = json.loads((temp / "package/package.json").read_text())
        if (
            manifest.get("id") != entry["id"]
            or manifest.get("version") != entry["version"]
        ):
            raise ValueError(
                "The package identity does not match the catalog."
            )
        if manifest.get("kind") not in ("cyberpunk2077", "application"):
            raise ValueError("This package needs a newer deckkit.")
        return temp / "package", manifest

    def install(
        self, package_id, allow_restart=False, progress=lambda text: None
    ):
        with self.lock():
            entry = self.entry(package_id)
            old = self.load_receipt(package_id)
            root = steam.steam_root(self.paths.home)
            account = steam.active_account(root)
            game = (
                steam.find_game(root)
                if entry["kind"] == "cyberpunk2077"
                else None
            )
            settings = steam.find_settings(root, game) if game else None
            if game:
                cyberpunk.ensure_closed()
            needs_shortcut = not (
                self.paths.state / "integration.json"
            ).exists()
            api_ready = self.steam_api.available()
            offline = needs_shortcut or not api_ready
            if offline and steam.steam_running() and not allow_restart:
                raise RuntimeError(
                    "This installation needs a Steam restart. "
                    "Use Install and restart Steam."
                )
            if offline and os.environ.get("SteamGameId"):
                raise RuntimeError(
                    "Run the Desktop installer to reconnect Steam integration."
                )
            self.paths.data.mkdir(parents=True, exist_ok=True)
            self.paths.packages.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=".install-", dir=self.paths.data
            ) as temporary:
                temp = Path(temporary)
                package, manifest = self.package_source(entry, temp, progress)
                runtime.install(self.paths, self.bundle, self.catalog_url)
                receipt = (
                    copy.deepcopy(old)
                    if old
                    else {"id": package_id, "files": {}, "settings": {}}
                )
                receipt.update(
                    {
                        "version": manifest["version"],
                        "manifest": manifest,
                        "receipt_path": str(self.paths.receipt(package_id)),
                        "steam_root": str(root),
                        "account": account,
                    }
                )
                if game:
                    receipt.update(game=str(game), settings_path=str(settings))
                # Failure restores the immediately preceding installation,
                # preserving edits made since the initial installation.
                owned = [Path(name) for name in receipt["files"]]
                if game:
                    owned += [
                        cyberpunk.ui_target(receipt),
                        cyberpunk.performance_target(receipt),
                        settings,
                    ]
                if game:
                    owned += cyberpunk.legacy_paths(receipt)

                snapshots = {
                    path: path.read_bytes() if path.exists() else None
                    for path in owned
                }
                launch_before = steam.launch_options(root, account)
                after = launch_before
                stopped = False
                destination = self.paths.packages / package_id
                retired = temp / "previous"
                promoted = False
                try:
                    progress("Configuring Steam")
                    if offline:
                        stopped = steam.close_steam()
                        launch_before = steam.launch_options(root, account)
                    if game:
                        wrapper = steam.command_string(
                            self.paths.command, "launch", package_id
                        )
                        if "launch_options" not in receipt:
                            original = steam.strip_legacy_launcher(
                                launch_before
                            )
                            after = steam.wrap_options(original, wrapper)
                            receipt["launch_options"] = {
                                "before": original,
                                "after": after,
                                "wrapper": wrapper,
                            }
                        else:
                            after = launch_before
                        self.save_receipt(receipt)
                        cyberpunk.install(receipt, package)
                        if offline:
                            steam.write_launch_options(root, account, after)
                        else:
                            self.steam_api.set_launch_options(after)
                    if offline:
                        marker = root / ".cef-enable-remote-debugging"
                        marker.touch(exist_ok=True)
                        steam.register_shortcut(
                            root,
                            account,
                            self.paths.command,
                            self.paths.runtime
                            / "current/_internal/data/icon.svg",
                        )
                        write_json(
                            self.paths.state / "integration.json",
                            {"steam_root": str(root), "account": account},
                        )
                    progress("Installing " + manifest["name"])
                    if destination.exists():
                        os.replace(destination, retired)
                    os.replace(package, destination)
                    promoted = True
                    if manifest["kind"] == "application":
                        app = (destination / manifest["entrypoint"]).resolve()
                        if (
                            destination.resolve() not in app.parents
                            or not app.is_file()
                        ):
                            raise ValueError("Invalid application entry point")
                        desktop = (
                            "[Desktop Entry]\nType=Application\n"
                            f"Name={manifest['name']}\n"
                            f'Exec="{app}"\nTerminal=false\n'
                        )
                        Journal(receipt).file(
                            self.paths.applications
                            / f"deckkit-{package_id}.desktop",
                            desktop.encode(),
                            0o755,
                        )
                    self.save_receipt(receipt)
                    return {"steam_closed": stopped, "installed": package_id}
                except Exception:
                    if promoted:
                        shutil.rmtree(destination, ignore_errors=True)
                        if retired.exists():
                            os.replace(retired, destination)
                    for path, content in snapshots.items():
                        if content is None:
                            path.unlink(missing_ok=True)
                        else:
                            write_atomic(path, content)
                    if game:
                        if offline:
                            steam.write_launch_options(
                                root, account, launch_before
                            )
                        elif launch_before != after:
                            self.steam_api.set_launch_options(launch_before)
                    if old:
                        self.save_receipt(old)
                    else:
                        self.paths.receipt(package_id).unlink(missing_ok=True)
                    raise

    def remove(self, package_id, progress=lambda text: None):
        with self.lock():
            receipt = self.load_receipt(package_id)
            if receipt is None:
                return {"preserved": []}
            if receipt["manifest"]["kind"] == "cyberpunk2077":
                cyberpunk.ensure_closed()
                progress("Restoring game settings")
                if not self.steam_api.available() and steam.steam_running():
                    raise RuntimeError(
                        "Restart Steam with CEF access enabled "
                        "before removing this package."
                    )
                root, account = Path(receipt["steam_root"]), receipt["account"]
                current = steam.launch_options(root, account)
                original = steam.unwrap_options(
                    current, receipt["launch_options"]
                )
                # QAM restoration runs once in Cyberpunk's app context,
                # then removes its launch hook.
                if receipt.get("steam_before"):
                    job = self.paths.state / "restore" / f"{package_id}.json"
                    write_json(
                        job,
                        {
                            "before": receipt["steam_before"],
                            "after": receipt.get("steam_after", {}),
                            "launch_options": original,
                            "steam_root": str(root),
                            "account": account,
                        },
                    )
                    original = steam.wrap_options(
                        original,
                        steam.command_string(
                            self.paths.command, "restore", package_id
                        ),
                    )
                if self.steam_api.available():
                    self.steam_api.set_launch_options(original)
                else:
                    steam.write_launch_options(root, account, original)
                preserved = Journal(receipt).restore(receipt["settings_path"])
            else:
                preserved = Journal(receipt).restore_files()
            progress("Removing " + receipt["manifest"]["name"])
            shutil.rmtree(self.paths.packages / package_id, ignore_errors=True)
            self.paths.receipt(package_id).unlink(missing_ok=True)
            return {"preserved": preserved}
