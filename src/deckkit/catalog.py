"""Read the bundled package list and refresh it on explicit request."""

import json

from .archive import open_url
from .paths import write_json


def load(data_root, state, config):
    bundled = json.loads((data_root / "catalog.json").read_text())
    url = config.get(
        "catalog_url",
        "https://github.com/"
        + bundled["repository"]
        + "/releases/latest/download/catalog.json",
    )

    cached = state / "catalog.json"
    catalog = json.loads(cached.read_text()) if cached.exists() else bundled

    return catalog, url


def fetch(url, state):
    with open_url(url, timeout=15) as response:
        catalog = json.load(response)

    if catalog.get("schema") != 1 or not isinstance(
        catalog.get("packages"), list
    ):
        raise ValueError("This catalog format is not supported.")

    write_json(state / "catalog.json", catalog)
    return catalog
