"""Install and update the portable application runtime."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import __version__, steam
from .archive import download, extract
from .paths import external_environment, write_atomic, write_json


def install(paths, bundle, catalog_url):
    if not (bundle / "deckkit").is_file():
        raise RuntimeError("Use the built installer to install deckkit.")
    target = paths.runtime / __version__
    if bundle.resolve() != target.resolve() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".runtime-", dir=target.parent))
        try:
            shutil.copytree(bundle, stage / "runtime", symlinks=True)
            os.replace(stage / "runtime", target)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    link = paths.runtime / ".current-new"
    link.unlink(missing_ok=True)
    link.symlink_to(target.name)
    os.replace(link, paths.runtime / "current")
    write_atomic(
        paths.command,
        b'#!/bin/sh\nexec "$(dirname "$0")/runtime/current/deckkit" "$@"\n',
        0o755,
    )
    paths.applications.mkdir(parents=True, exist_ok=True)
    desktop = (
        "[Desktop Entry]\nType=Application\nName=deckkit\n"
        f"Exec={steam.command_string(paths.command, 'catalog')}\n"
        f"Icon={paths.runtime / 'current/_internal/data/icon.svg'}\n"
        "Terminal=false\nCategories=Game;Utility;\n"
    )
    write_atomic(
        paths.applications / "deckkit.desktop",
        desktop.encode(),
        0o755,
    )
    if not paths.config.exists():
        write_json(paths.config, {"catalog_url": catalog_url})


def update(paths, info, progress=lambda text: None):
    if not info or info["version"] == __version__:
        return
    with tempfile.TemporaryDirectory(
        prefix=".update-", dir=paths.data
    ) as temporary:
        temp = Path(temporary)
        progress("Downloading deckkit")
        download(
            info["asset"]["url"],
            temp / "runtime.tar.gz",
            info["asset"]["sha256"],
        )
        extract(temp / "runtime.tar.gz", temp / "runtime")
        candidate = temp / "runtime/deckkit"
        result = subprocess.check_output(
            [str(candidate), "--version"],
            env=external_environment(),
            timeout=20,
            text=True,
        ).strip()
        if result != info["version"]:
            raise RuntimeError(
                "The runtime version does not match the catalog."
            )
        target = paths.runtime / result
        if target.exists():
            shutil.rmtree(target)
        os.replace(temp / "runtime", target)
        link = paths.runtime / ".current-new"
        link.symlink_to(target.name)
        os.replace(link, paths.runtime / "current")
        progress("deckkit updated. Reopen the catalog.")
