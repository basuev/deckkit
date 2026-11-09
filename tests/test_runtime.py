"""Keep the installed runtime when an update fails verification."""

import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from support import fixture

from deckkit import steam


class Runtime(unittest.TestCase):
    def test_update_catalog_and_runtime_with_failed_update_isolation(self):
        for case in ("valid", "wrong hash", "wrong version"):
            with (
                self.subTest(case=case),
                tempfile.TemporaryDirectory() as directory,
                patch.object(steam, "steam_running", return_value=False),
                patch.object(steam, "game_running", return_value=False),
            ):
                data = fixture(Path(directory))
                installer = data["installer"]
                installer.install("cyberpunk2077")
                previous = installer.paths.runtime.joinpath(
                    "current"
                ).resolve()
                settings = data["settings"].read_bytes()

                content = io.BytesIO()
                version = "0.3.0" if case == "wrong version" else "0.2.0"
                executable = f"#!/bin/sh\necho {version}\n".encode()
                with tarfile.open(fileobj=content, mode="w:gz") as archive:
                    entry = tarfile.TarInfo("deckkit")
                    entry.mode = 0o755
                    entry.size = len(executable)
                    archive.addfile(entry, io.BytesIO(executable))

                downloads = {"/runtime.tar.gz": content.getvalue()}

                class Server(BaseHTTPRequestHandler):
                    def do_GET(self):
                        body = downloads.get(self.path)
                        if body is None:
                            self.send_error(404)
                            return
                        self.send_response(200)
                        self.end_headers()
                        self.wfile.write(body)

                    def log_message(self, *args):
                        pass

                server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:
                    url = f"http://127.0.0.1:{server.server_port}"
                    catalog = dict(installer.catalog)
                    checksum = hashlib.sha256(content.getvalue()).hexdigest()
                    catalog["runtime"] = {
                        "version": "0.2.0",
                        "asset": {
                            "url": url + "/runtime.tar.gz",
                            "sha256": "0" * 64
                            if case == "wrong hash"
                            else checksum,
                        },
                    }
                    downloads["/catalog.json"] = json.dumps(catalog).encode()
                    installer.catalog_url = url + "/catalog.json"
                    installer.refresh()

                    if case == "valid":
                        installer.update_runtime()
                        current = installer.paths.runtime.joinpath(
                            "current"
                        ).resolve()
                        self.assertEqual(current.name, "0.2.0")
                        self.assertEqual(
                            subprocess.check_output(
                                [str(current / "deckkit"), "--version"]
                            ),
                            b"0.2.0\n",
                        )
                    else:
                        with self.assertRaises(RuntimeError):
                            installer.update_runtime()
                        self.assertEqual(
                            installer.paths.runtime.joinpath(
                                "current"
                            ).resolve(),
                            previous,
                        )

                    self.assertEqual(data["settings"].read_bytes(), settings)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
