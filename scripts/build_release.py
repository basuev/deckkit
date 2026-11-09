"""Build the portable runtime, packages and pinned Desktop installer."""

import argparse
import base64
import hashlib
import importlib.metadata
import json
import runpy
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
__version__ = runpy.run_path(ROOT / "src/deckkit/__init__.py")["__version__"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(source, target):
    with tarfile.open(target, "w:gz", format=tarfile.PAX_FORMAT) as out:
        for path in sorted(source.iterdir()):
            out.add(path, arcname=path.name)


def desktop_entry(bootstrap):
    encoded = base64.b64encode(bootstrap.encode()).decode()
    command = f"printf %%s {encoded} | base64 -d | sh"
    escaped = (
        command.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    return (
        "[Desktop Entry]\nType=Application\nName=Install deckkit\n"
        "Comment=Cyberpunk profiles and independent Steam Deck tools\n"
        f'Exec=sh -c "{escaped}"\n'
        "Icon=system-software-install\nTerminal=false\nStartupNotify=true\n"
    )


def copy_runtime_licenses(runtime):
    directory = runtime / "LICENSES/runtime"
    directory.mkdir(parents=True, exist_ok=True)
    libraries = {}
    for line in subprocess.check_output(
        ["/sbin/ldconfig", "-p"], text=True
    ).splitlines():
        if " => " in line:
            name, path = line.strip().split(" => ")
            libraries[name.split()[0]] = Path(path)

    shared = Path(sysconfig.get_config_var("DESTSHARED"))
    packages, components = {}, {}
    for library in sorted((runtime / "_internal").rglob("*")):
        if not library.is_file() or not (
            library.name.endswith(".so") or ".so." in library.name
        ):
            continue
        source = libraries.get(library.name, shared / library.name)
        for candidate in dict.fromkeys((source.resolve(), source)):
            owner = subprocess.run(
                ["dpkg-query", "-S", str(candidate)],
                text=True,
                capture_output=True,
            )
            if owner.returncode == 0:
                break
        else:
            raise RuntimeError(f"No source package for {library.name}")
        package = owner.stdout.split(": ", 1)[0].split(":", 1)[0]
        if package not in packages:
            notice = Path("/usr/share/doc") / package / "copyright"
            shutil.copyfile(notice, directory / f"{package}.txt")
            packages[package] = subprocess.check_output(
                ["dpkg-query", "-W", "-f=${Version}", package], text=True
            ).strip()
        components[str(library.relative_to(runtime))] = package

    distribution = importlib.metadata.distribution("pyinstaller")
    notice = next(
        path for path in distribution.files if path.name == "COPYING.txt"
    )
    shutil.copyfile(
        distribution.locate_file(notice), directory / "PyInstaller.txt"
    )
    (directory / "index.json").write_text(
        json.dumps(
            {
                "packages": packages,
                "libraries": components,
                "pyinstaller": distribution.version,
            },
            indent=2,
        )
        + "\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default="basuev/deckkit")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    import re

    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        parser.error("Use owner/repository")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    version = __version__
    release = (
        f"https://github.com/{args.repository}/releases/download/v{version}"
    )
    catalog = json.loads((ROOT / "assets/catalog.json").read_text())
    catalog["repository"] = args.repository
    for entry in catalog["packages"]:
        source = ROOT / "assets/packages" / entry["id"]
        asset = output / f"{entry['id']}-{entry['version']}.tar.gz"
        archive(source, asset)
        entry["asset"] = {
            "url": release + "/" + asset.name,
            "sha256": sha(asset),
        }
    with tempfile.TemporaryDirectory(prefix="deckkit-build-") as directory:
        temp = Path(directory)
        data = temp / "data"
        data.mkdir()
        (data / "catalog.json").write_text(
            json.dumps(catalog, indent=2) + "\n"
        )
        shutil.copy2(ROOT / "assets/icon.svg", data / "icon.svg")
        shutil.copy2(ROOT / "assets/wordmark.png", data / "wordmark.png")
        for entry in catalog["packages"]:
            shutil.copytree(
                ROOT / "assets/packages" / entry["id"],
                data / "packages" / entry["id"],
            )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onedir",
                "--name",
                "deckkit",
                "--paths",
                str(ROOT / "src"),
                "--distpath",
                str(output / "runtime"),
                "--workpath",
                str(temp / "work"),
                "--specpath",
                str(temp),
                "--add-data",
                str(data) + ":data",
                str(ROOT / "scripts/freeze_entry.py"),
            ],
            check=True,
        )
    runtime = output / "runtime/deckkit"
    (runtime / "LICENSES").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", runtime / "LICENSES/deckkit.txt")
    shutil.copy2(
        ROOT / "assets/packages/cyberpunk2077/NOTICE.md",
        runtime / "LICENSES/Cyberpunk-UI.md",
    )
    copy_runtime_licenses(runtime)
    runtime_archive = output / "deckkit-linux-x86_64.tar.gz"
    archive(runtime, runtime_archive)
    catalog["runtime"] = {
        "version": version,
        "asset": {
            "url": release + "/" + runtime_archive.name,
            "sha256": sha(runtime_archive),
        },
    }
    (output / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    bootstrap = (
        (ROOT / "scripts/bootstrap.sh.in")
        .read_text()
        .replace("@URL@", release + "/" + runtime_archive.name)
        .replace("@SHA@", sha(runtime_archive))
    )
    desktop = desktop_entry(bootstrap)
    (output / "Install.desktop").write_text(desktop)
    (output / "Install.desktop").chmod(0o755)
    names = ["Install.desktop", runtime_archive.name, "catalog.json"] + [
        f"{e['id']}-{e['version']}.tar.gz" for e in catalog["packages"]
    ]
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha(output / name)}  {name}\n" for name in names)
    )
    print(
        json.dumps(
            {
                "version": version,
                "repository": args.repository,
                "assets": names,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
