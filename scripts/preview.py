"""Run the real UI against a disposable game and simulated Steam transport."""

import argparse
import json
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from support import fixture

from deckkit import __version__, catalog_ui, profiles, selector, steam, ui

MOCK_NAMES = {
    "games": (
        "Hades II",
        "Elden Ring",
        "Baldur's Gate 3",
        "Control",
        "Death Stranding",
        "Disco Elysium",
        "DOOM Eternal",
        "Fallout 4",
        "Forza Horizon 5",
        "Hollow Knight",
        "Monster Hunter Rise",
        "No Man's Sky",
        "Portal 2",
        "Red Dead Redemption 2",
        "Resident Evil 4",
        "Stardew Valley",
        "The Witcher 3",
        "Titanfall 2",
        "Valheim",
        "Yakuza 0",
        "Half-Life 2",
        "Armored Core VI",
        "Celeste",
        "Dead Cells",
    ),
    "device": (
        "Charge limit",
        "Display profile",
        "Audio routing",
        "Touchpad settings",
        "Controller calibration",
        "Bluetooth reconnect",
        "Docked display",
        "Sleep settings",
        "Wi-Fi power",
        "Fan profile",
        "Storage cleanup",
        "Screen brightness",
        "Keyboard layout",
        "External controller",
        "Microphone settings",
        "Touchscreen settings",
    ),
    "tools": (
        "Screenshot export",
        "Quick notes",
        "Save backup",
        "Session log",
        "File transfer",
        "Storage viewer",
        "Download queue",
        "Audio recorder",
        "Clipboard",
        "Game shortcuts",
        "Benchmark log",
        "Photo browser",
        "Controller tester",
        "Display tester",
        "Network check",
        "Archive viewer",
    ),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "screen",
        nargs="?",
        default="catalog",
        choices=("catalog", "installer", "selector"),
    )
    parser.add_argument("--size", default="920x600")
    parser.add_argument("--error", action="store_true")
    args = parser.parse_args()
    width, height = map(int, args.size.split("x"))

    with tempfile.TemporaryDirectory(prefix="deckkit-preview-") as directory:
        data = fixture(Path(directory))
        installer = data["installer"]
        requested = []
        roots = []
        mock_receipts = {}
        real_window = ui.window
        real_install = installer.install
        real_remove = installer.remove
        real_receipt = installer.load_receipt

        for category, names in MOCK_NAMES.items():
            for index, name in enumerate(names):
                installer.catalog["packages"].append(
                    {
                        "id": f"preview-{category}-{index}",
                        "name": name,
                        "category": category,
                        "version": "0.1.0",
                        "summary": "Preview example. "
                        + {
                            "games": "Settings for this game only.",
                            "device": "Settings shared across the device.",
                            "tools": "An independent utility.",
                        }[category],
                        "kind": "application",
                    }
                )

        def window(title, **kwargs):
            root = real_window(title, width=width, height=height)
            root.title(title + " Preview")
            roots.append(root)
            return root

        def receipt(package_id):
            if package_id == "cyberpunk2077":
                return real_receipt(package_id)
            return mock_receipts.get(package_id)

        def install(
            package_id, allow_restart=False, progress=lambda text: None
        ):
            if package_id == "cyberpunk2077":
                return real_install(package_id, allow_restart, progress)
            entry = installer.entry(package_id)
            mock_receipts[package_id] = {
                "version": entry["version"],
                "manifest": {"kind": "application", "entrypoint": "preview"},
            }
            return {"installed": package_id}

        def remove(package_id, progress=lambda text: None):
            if package_id == "cyberpunk2077":
                return real_remove(package_id, progress)
            mock_receipts.pop(package_id, None)
            return {"preserved": []}

        def refresh():
            if args.error:
                raise RuntimeError("The update server could not be reached.")
            entry = installer.entry("cyberpunk2077")
            entry["version"] = "0.2.0"
            manifest_path = (
                data["bundle"] / "assets/packages/cyberpunk2077/package.json"
            )
            manifest = json.loads(manifest_path.read_text())
            manifest["version"] = entry["version"]
            manifest_path.write_text(json.dumps(manifest))
            for mock in installer.packages()[1:]:
                mock["version"] = "0.2.0"
            installer.catalog["runtime"] = {"version": "0.2.0"}

        def update_runtime(progress):
            progress("Updating deckkit")
            installer.catalog["runtime"] = {"version": __version__}

        with ExitStack() as stack:
            replacements = (
                (steam, "steam_running", lambda: False),
                (steam, "game_running", lambda: False),
                (catalog_ui, "window", window),
                (selector, "window", window),
                (ui, "window", window),
                (installer, "install", install),
                (installer, "remove", remove),
                (installer, "load_receipt", receipt),
                (installer, "refresh", refresh),
                (installer, "update_runtime", update_runtime),
                (
                    catalog_ui,
                    "return_to_gaming",
                    lambda home: roots[-1].event_generate("<Escape>"),
                ),
                (
                    catalog_ui.subprocess,
                    "Popen",
                    lambda command, **kwargs: requested.append(command),
                ),
            )
            for target, name, replacement in replacements:
                stack.enter_context(patch.object(target, name, replacement))

            if args.screen != "installer":
                installer.install("cyberpunk2077")
                profiles.apply(installer, "cyberpunk2077", 45, 175)
            if args.screen == "selector":
                selector.selector(
                    installer, installer.load_receipt("cyberpunk2077")
                )
                return

            while True:
                requested.clear()
                catalog_ui.catalog(
                    installer,
                    "cyberpunk2077" if args.screen == "installer" else None,
                )
                if not requested:
                    break
                if requested[-1][0] == "steam":
                    selector.selector(
                        installer, installer.load_receipt("cyberpunk2077")
                    )
                else:
                    ui.error_window("This package is a preview example.")


if __name__ == "__main__":
    main()
