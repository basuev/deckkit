"""Record only owned changes and preserve later edits during removal."""

import base64
import hashlib
from pathlib import Path

from .paths import write_atomic, write_json


def digest(content):
    return hashlib.sha256(content).hexdigest() if content is not None else None


class Journal:
    def __init__(self, receipt):
        self.receipt = receipt
        receipt.setdefault("files", {})
        receipt.setdefault("settings", {})

    def flush(self):
        if self.receipt.get("receipt_path"):
            write_json(self.receipt["receipt_path"], self.receipt)

    def file(self, path, content, mode=0o644):
        path = Path(path)
        key = str(path)
        if key not in self.receipt["files"]:
            before = path.read_bytes() if path.exists() else None
            self.receipt["files"][key] = {
                "before": base64.b64encode(before).decode()
                if before is not None
                else None,
                "mode": path.stat().st_mode & 0o777 if path.exists() else mode,
            }
        record = self.receipt["files"][key]
        record["after"] = digest(content)
        self.flush()
        if content is None:
            path.unlink(missing_ok=True)
        else:
            write_atomic(path, content, mode)

    def setting(self, group, option, values):
        key = group + "/" + option["name"]
        if key not in self.receipt["settings"]:
            self.receipt["settings"][key] = {
                "group": group,
                "name": option["name"],
                "before": {
                    k: option[k] for k in ("value", "index") if k in option
                },
            }
        option.update(values)
        self.receipt["settings"][key]["after"] = {
            k: option[k] for k in ("value", "index") if k in option
        }

    def restore_files(self):
        preserved = []
        for name, record in self.receipt["files"].items():
            path = Path(name)
            current = path.read_bytes() if path.exists() else None
            if digest(current) != record["after"]:
                preserved.append(name)
                continue
            before = record["before"]
            if before is None:
                path.unlink(missing_ok=True)
            else:
                write_atomic(path, base64.b64decode(before), record["mode"])
        return preserved

    def restore_settings(self, data):
        for group in data["data"]:
            for option in group.get("options", []):
                record = self.receipt["settings"].get(
                    group["group_name"] + "/" + option["name"]
                )
                if (
                    record
                    and {
                        k: option[k] for k in ("value", "index") if k in option
                    }
                    == record["after"]
                ):
                    for key in ("value", "index"):
                        if key in record["before"]:
                            option[key] = record["before"][key]
                        else:
                            option.pop(key, None)

    def restore(self, settings):
        import json

        preserved = self.restore_files()
        if Path(settings).exists():
            data = json.loads(Path(settings).read_text())
            self.restore_settings(data)
            write_atomic(
                settings, (json.dumps(data, indent=4) + "\n").encode()
            )
        return preserved
