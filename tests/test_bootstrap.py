"""An invalid download must never reach the installer entry point."""

import hashlib
import io
import os
import runpy
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Bootstrap(unittest.TestCase):
    def test_desktop_entry_preserves_shell_command(self):
        build = runpy.run_path(str(ROOT / "scripts/build_release.py"))
        script = 'printf "%s" "bootstrap passed"\n'
        entry = build["desktop_entry"](script)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Install.desktop"
            path.write_text(entry)
            if shutil.which("desktop-file-validate"):
                subprocess.run(
                    ["desktop-file-validate", str(path)], check=True
                )
            command = next(
                line.removeprefix("Exec=")
                for line in entry.splitlines()
                if line.startswith("Exec=")
            )
            self.assertNotIn("%", command.replace("%%", ""))
            argv = shlex.split(command.replace("%%", "%"))
            result = subprocess.run(argv, capture_output=True, check=True)
            self.assertEqual(result.stdout, b"bootstrap passed")

    def test_verified_download_and_failure_paths(self):
        for case in ("verified", "wrong hash", "invalid archive"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                source = root / "download.tar.gz"
                with tarfile.open(source, "w:gz") as archive:
                    script = (
                        b"#!/bin/sh\n"
                        b'printf "%s" "$*" > "$DECKKIT_TEST_MARKER"\n'
                    )
                    entry = tarfile.TarInfo("deckkit")
                    entry.size = len(script)
                    entry.mode = 0o755
                    archive.addfile(entry, io.BytesIO(script))

                if case == "invalid archive":
                    source.write_bytes(b"not a tar archive")
                checksum = hashlib.sha256(source.read_bytes()).hexdigest()
                if case == "wrong hash":
                    checksum = "0" * 64

                # Force the progress-dialog pipeline, where set -e alone
                # does not provide reliable failure propagation.
                tools = root / "tools"
                tools.mkdir()
                curl = tools / "curl"
                curl.write_text(
                    '#!/bin/sh\nwhile [ "$1" != "--output" ]; do shift; done\n'
                    'cp "$DECKKIT_TEST_DOWNLOAD" "$2"\n'
                )
                zenity = tools / "zenity"
                zenity.write_text("#!/bin/sh\ncat >/dev/null\n")
                for tool in (curl, zenity):
                    tool.chmod(0o755)

                template = (ROOT / "scripts/bootstrap.sh.in").read_text()
                script = root / "install.sh"
                script.write_text(
                    template.replace(
                        "@URL@", "https://example.invalid/runtime"
                    ).replace("@SHA@", checksum)
                )
                marker = root / "executed"
                env = dict(os.environ)
                env.update(
                    PATH=str(tools) + os.pathsep + env["PATH"],
                    DECKKIT_TEST_DOWNLOAD=str(source),
                    DECKKIT_TEST_MARKER=str(marker),
                )
                result = subprocess.run(
                    ["sh", str(script)],
                    env=env,
                    capture_output=True,
                    timeout=10,
                )

                if case == "verified":
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        marker.read_text(), "installer cyberpunk2077"
                    )
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(marker.exists())
