"""Download verified release archives and extract their files."""

import hashlib
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path


def download(url, target, expected):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http"
        and parsed.hostname in ("localhost", "127.0.0.1", "::1")
    ):
        raise ValueError("Downloads need HTTPS.")
    digest = hashlib.sha256()
    with (
        urllib.request.urlopen(url, timeout=30) as inp,
        Path(target).open("wb") as out,
    ):
        while True:
            chunk = inp.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
    if digest.hexdigest() != expected:
        Path(target).unlink(missing_ok=True)
        raise RuntimeError(
            "The download failed its integrity check. Try installing again."
        )


def extract(archive, target):
    target = Path(target).resolve()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            destination = (target / member.name).resolve()
            if destination != target and target not in destination.parents:
                raise ValueError(
                    "The package contains a path outside its directory."
                )
            if not (
                member.isfile()
                or member.isdir()
                or member.issym()
                or member.islnk()
            ):
                raise ValueError("The package contains a special device file.")
            if member.issym() or member.islnk():
                link = (
                    destination.parent if member.issym() else target
                ) / member.linkname
                if (
                    target not in link.resolve().parents
                    and link.resolve() != target
                ):
                    raise ValueError("The package contains an external link.")
            tar.extract(member, target, filter="fully_trusted")
