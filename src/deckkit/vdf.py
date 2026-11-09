"""Lossless edits of Steam text VDF and binary shortcut records."""

import re
import struct

TOKEN = re.compile(r'//[^\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+')


def quote(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse(text):
    tokens = [
        m for m in TOKEN.finditer(text) if not m.group().startswith("//")
    ]
    pos = 0

    def scalar(token):
        s = token.group()
        return re.sub(r'\\([\\"])', r"\1", s[1:-1]) if s.startswith('"') else s

    def nodes(nested=False):
        nonlocal pos
        result = []
        while pos < len(tokens):
            token = tokens[pos]
            if token.group() == "}":
                if not nested:
                    raise ValueError("Unexpected VDF closing brace")
                pos += 1
                return result
            pos += 1
            if pos >= len(tokens):
                raise ValueError("Incomplete VDF value")
            value = tokens[pos]
            pos += 1
            node = {
                "key": scalar(token),
                "start": token.start(),
                "value_start": value.start(),
            }
            if value.group() == "{":
                node["children"] = nodes(True)
                node["close"] = tokens[pos - 1].start()
            else:
                node["value"] = scalar(value)
            node["end"] = tokens[pos - 1].end()
            result.append(node)
        if nested:
            raise ValueError("Unclosed VDF object")
        return result

    return nodes()


def child(nodes, key):
    return next((n for n in nodes if n["key"].lower() == key.lower()), None)


def lookup(text, path):
    nodes = parse(text)
    node = None
    for key in path:
        node = child(nodes, key)
        if node is None:
            return None
        nodes = node.get("children", [])
    return node


def set_value(text, path, value):
    node = lookup(text, path)
    if node:
        if "children" in node:
            raise ValueError("Cannot replace a VDF object with a scalar")
        if value is None:
            return text[: node["start"]] + text[node["end"] :]
        return text[: node["value_start"]] + quote(value) + text[node["end"] :]
    if value is None:
        return text
    parent = lookup(text, path[:-1]) if len(path) > 1 else None
    if len(path) > 1 and parent is None:
        text = ensure_object(text, path[:-1])
        parent = lookup(text, path[:-1])
    at = parent["close"] if parent else len(text)
    indent = "\t" * (len(path) - 1)
    addition = f"\n{indent}{quote(path[-1])}\t\t{quote(value)}\n{indent[:-1]}"
    return text[:at] + addition + text[at:]


def ensure_object(text, path):
    if not path or lookup(text, path):
        return text
    text = ensure_object(text, path[:-1])
    parent = lookup(text, path[:-1]) if len(path) > 1 else None
    at = parent["close"] if parent else len(text)
    indent = "\t" * (len(path) - 1)
    addition = f"\n{indent}{quote(path[-1])}\n{indent}{{\n{indent}}}\n"
    return text[:at] + addition + text[at:]


def decode_binary(data):
    pos = 0

    def string():
        nonlocal pos
        end = data.index(b"\0", pos)
        value = data[pos:end].decode("utf-8", "surrogateescape")
        pos = end + 1
        return value

    def obj():
        nonlocal pos
        result = []
        while pos < len(data):
            kind = data[pos]
            pos += 1
            if kind == 8:
                return result
            name = string()
            if kind == 0:
                value = obj()
            elif kind == 1:
                value = string()
            elif kind in (2, 3, 4, 6, 7, 10):
                size = 8 if kind in (7, 10) else 4
                value = data[pos : pos + size]
                if len(value) != size:
                    raise ValueError("Truncated binary VDF")
                pos += size
            else:
                raise ValueError(f"Unsupported binary VDF type {kind}")
            result.append([kind, name, value])
        raise ValueError("Unclosed binary VDF")

    result = obj()
    if pos != len(data):
        raise ValueError("Trailing binary VDF data")
    return result


def encode_binary(nodes):
    out = bytearray()
    for kind, name, value in nodes:
        out.extend(
            bytes([kind]) + name.encode("utf-8", "surrogateescape") + b"\0"
        )
        if kind == 0:
            out.extend(encode_binary(value))
        elif kind == 1:
            out.extend(value.encode("utf-8", "surrogateescape") + b"\0")
        else:
            out.extend(value)
    out.append(8)
    return bytes(out)


def integer(value):
    return struct.pack("<I", value & 0xFFFFFFFF)
