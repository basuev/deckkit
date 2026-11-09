"""Catalog and package requests must verify the configured CA trust store."""

import hashlib
import json
import os
import ssl
import subprocess
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from deckkit import catalog
from deckkit.archive import download


class HTTPS(unittest.TestCase):
    def test_catalog_and_archive_verify_the_host_trust_store(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            certificate = root / "server.pem"
            key = root / "server.key"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    str(key),
                    "-out",
                    str(certificate),
                    "-days",
                    "1",
                    "-subj",
                    "/CN=localhost",
                    "-addext",
                    "subjectAltName=IP:127.0.0.1",
                ],
                check=True,
                capture_output=True,
            )
            body = json.dumps({"schema": 1, "packages": []}).encode()

            class Server(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certificate, key)
            server.socket = context.wrap_socket(
                server.socket, server_side=True
            )
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            url = f"https://127.0.0.1:{server.server_port}/data"
            checksum = hashlib.sha256(body).hexdigest()
            target = root / "download"

            try:
                with patch.dict(
                    os.environ,
                    SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt",
                ):
                    with self.assertRaises(urllib.error.URLError):
                        catalog.fetch(url, root)
                    with self.assertRaises(urllib.error.URLError):
                        download(url, target, checksum)
                self.assertFalse((root / "catalog.json").exists())
                self.assertFalse(target.exists())

                with patch.dict(os.environ, SSL_CERT_FILE=str(certificate)):
                    self.assertEqual(catalog.fetch(url, root)["schema"], 1)
                    download(url, target, checksum)
                self.assertEqual(target.read_bytes(), body)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
