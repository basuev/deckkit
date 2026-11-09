"""Own Cyberpunk settings and UI files without rewriting unrelated choices."""

import json
from pathlib import Path

from . import steam
from .journal import Journal, digest
from .paths import write_atomic

FPS_LIMITS = [None, 45]
UI_SCALES = [100, 150, 175]


def ensure_closed():
    if steam.game_running():
        raise RuntimeError("Close Cyberpunk before changing its settings.")


def patch_options(data, values, journal):
    found = set()
    for group in data["data"]:
        for option in group.get("options", []):
            name = option.get("name")
            if name not in values:
                continue

            value = values[name]
            changes = {"value": value}
            if value in option.get("values", []):
                changes["index"] = option["values"].index(value)
            elif "index" in option:
                indexes = {
                    "QuickPresets": 0,
                    "ResolutionScaling": 1,
                    "FSR2": 3,
                    "FrameGeneration": 0,
                    "VSync": 0,
                    "WindowMode": 1,
                    "Resolution": 0,
                }
                if name in indexes:
                    changes["index"] = indexes[name]

            journal.setting(group["group_name"], option, changes)
            found.add(name)

    return found


def ui_target(receipt):
    return Path(receipt["game"]) / "archive/pc/mod/deckkit-ui.archive"


def performance_target(receipt):
    return (
        Path(receipt["game"])
        / "engine/config/platform/pc/deckkit-performance.ini"
    )


def legacy_paths(receipt):
    game = Path(receipt["game"])
    return [
        game / "archive/pc/mod/codex-deck-ui.archive",
        game / "engine/config/platform/pc/codex-performance.ini",
    ]


def migrate_files(receipt, package_root):
    """Adopt recognized personal files once, leaving modified files alone."""
    old_ui, old_performance = legacy_paths(receipt)
    expected = [
        {p["sha256"] for p in receipt["manifest"]["profiles"].values()},
        {
            digest(
                (Path(package_root) / "deckkit-performance.ini").read_bytes()
            )
        },
    ]
    migrated = False

    for path, hashes in zip((old_ui, old_performance), expected):
        if not path.exists():
            continue

        content = path.read_bytes()
        if digest(content) not in hashes:
            continue

        # Known personal artifacts belong to us, rather than to a pre-existing
        # third-party mod. Removal must not resurrect that old installation.
        receipt["files"].setdefault(
            str(path),
            {"before": None, "after": digest(content), "mode": 0o644},
        )
        journal = Journal(receipt)
        if path == old_ui and not ui_target(receipt).exists():
            journal.file(ui_target(receipt), content)
        journal.file(path, None)
        migrated = True

    return migrated


def selected(receipt):
    target = ui_target(receipt)
    archive_hash = digest(target.read_bytes()) if target.exists() else None
    profiles = receipt["manifest"]["profiles"]
    ui_scale = next(
        (int(n) for n, p in profiles.items() if p["sha256"] == archive_hash),
        100,
    )

    data = json.loads(Path(receipt["settings_path"]).read_text())
    options = {
        option["name"]: option["value"]
        for group in data["data"]
        for option in group.get("options", [])
        if "value" in option
    }
    fps_limit = (
        45
        if options.get("MaximumFPS_OnOff")
        and options.get("MaximumFPS_Value") == 45
        else None
    )

    return fps_limit, ui_scale


def read_ui_profile(receipt, package_root, ui_scale):
    if ui_scale not in UI_SCALES:
        raise ValueError("Unknown interface scale")
    if ui_scale == 100:
        return None

    profile = receipt["manifest"]["profiles"][str(ui_scale)]
    content = (Path(package_root) / profile["file"]).read_bytes()
    if digest(content) != profile["sha256"]:
        raise RuntimeError("The UI profile failed its integrity check.")

    return content


def apply(receipt, package_root, fps_limit, ui_scale, graphics=False):
    ensure_closed()
    if fps_limit not in FPS_LIMITS:
        raise ValueError("Unknown FPS limit")

    content = read_ui_profile(receipt, package_root, ui_scale)
    path = Path(receipt["settings_path"])
    data = json.loads(path.read_text())
    values = dict(receipt["manifest"]["graphics"]) if graphics else {}
    values.update(
        {
            "MaximumFPS_OnOff": fps_limit is not None,
            "MaximumFPS_Value": 45,
            "VSync": "UI-Settings-Video-QualitySetting-Off",
        }
    )

    journal = Journal(receipt)
    found = patch_options(data, values, journal)
    if not {"MaximumFPS_OnOff", "MaximumFPS_Value", "VSync"} <= found:
        raise RuntimeError("The game settings format is not supported.")

    journal.file(ui_target(receipt), content)
    write_atomic(path, (json.dumps(data, indent=4) + "\n").encode())
    receipt.pop("selection", None)


def install(receipt, package_root):
    ensure_closed()
    migrated = migrate_files(receipt, package_root)
    fps_limit, ui_scale = (
        selected(receipt)
        if migrated or receipt.get("settings")
        else (None, 150)
    )

    apply(receipt, package_root, fps_limit, ui_scale, graphics=True)
    content = (Path(package_root) / "deckkit-performance.ini").read_bytes()
    Journal(receipt).file(performance_target(receipt), content)
