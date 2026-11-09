"""Pre-launch selection and deferred Steam-profile restoration."""

import json
import os

from .paths import external_environment


def execute(command, optimize=True):
    if not command:
        raise RuntimeError("Start Cyberpunk through its Steam Play button.")
    env = external_environment()
    if optimize:
        env.update(DISABLE_LSFG="1", VKD3D_SWAPCHAIN_LATENCY_FRAMES="2")
        for flag in ("--launcher-skip", "-skipStartScreen"):
            if flag not in command:
                command.append(flag)
    os.execvpe(command[0], command, env)


def launch(installer, package_id, command, interactive=True):

    receipt = installer.load_receipt(package_id)
    if receipt is None:
        raise RuntimeError("The Cyberpunk package is not installed.")
    if interactive:
        from .selector import selector

        accepted = selector(installer, receipt)
    else:
        from . import cyberpunk, profiles

        fps_limit, ui_scale = cyberpunk.selected(receipt)
        profiles.apply(installer, package_id, fps_limit, ui_scale, steam=True)
        accepted = True

    if accepted:
        execute(command)


def restore(installer, package_id, command):
    from .selector import restore_window

    job_path = installer.paths.state / "restore" / f"{package_id}.json"
    if not job_path.exists():
        raise RuntimeError("The Steam restoration record is missing.")
    job = json.loads(job_path.read_text())
    with installer.lock():
        if not restore_window(installer, job):
            return
        # Restore the command while Cyberpunk owns the Steam profile.
        installer.steam_api.set_launch_options(job["launch_options"])
        job_path.unlink()
    execute(command, optimize=False)
