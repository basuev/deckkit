"""Shared profile operations for the CLI and controller interface."""

from . import cyberpunk


def apply(
    installer, package_id, fps_limit, ui_scale, steam=False, pump=lambda: None
):
    with installer.lock():
        receipt = installer.load_receipt(package_id)
        if receipt is None:
            raise RuntimeError("The Cyberpunk package is not installed.")

        if steam:
            installer.steam_api.wait_for_game(pump)
            if not receipt.get("steam_before"):
                receipt["steam_before"] = installer.steam_api.snapshot()
                installer.save_receipt(receipt)

            receipt["steam_after"] = (
                installer.steam_api.apply_display_settings()
            )
            installer.save_receipt(receipt)

        cyberpunk.apply(
            receipt,
            installer.paths.packages / package_id,
            fps_limit,
            ui_scale,
        )
        installer.save_receipt(receipt)

    return {"fps_limit": fps_limit, "ui_scale": ui_scale}


def restore_display(installer, job, pump=lambda: None):
    installer.steam_api.wait_for_game(pump)
    current = installer.steam_api.snapshot()
    values = {
        key: value
        for key, value in job["before"].items()
        if key in job["after"] and current.get(key) == job["after"][key]
    }

    if values:
        installer.steam_api.set_settings(values)
