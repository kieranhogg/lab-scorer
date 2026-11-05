"""A small JSONPath subset for lab checks, so no extra dependency is needed.

Supported: $, .key, ['key'], ["key"], [0], [-1], [*] and .*
"""
import json
import re

WILDCARD = object()
TOKEN = re.compile(r"""\.\*|\[\*\]|\.(\w+)|\[(-?\d+)\]|\['([^']*)'\]|\["([^"]*)"\]""")


def parse(path: str) -> list:
    """Split a JSONPath into keys, indexes and WILDCARD. Raises ValueError for unsupported syntax."""
    if not path.startswith("$"):
        raise ValueError(f"JSONPath must start with $: {path}")
    steps = []
    position = 1
    while position < len(path):
        match = TOKEN.match(path, position)
        if not match:
            raise ValueError(f"Unsupported JSONPath {path} at position {position}")
        name, index, single, double = match.groups()
        if match[0] in (".*", "[*]"):
            steps.append(WILDCARD)
        elif index is not None:
            steps.append(int(index))
        else:
            steps.append(next(part for part in (name, single, double) if part is not None))
        position = match.end()
    return steps


def lookup(data, path: str) -> tuple[bool, object]:
    """Return (found, value). A path with a wildcard gives the list of every match."""
    steps = parse(path)
    nodes = [data]
    for step in steps:
        found = []
        for node in nodes:
            if step is WILDCARD:
                found += list(node.values()) if isinstance(node, dict) else list(node) if isinstance(node, list) else []
            elif isinstance(step, int) and isinstance(node, list) and -len(node) <= step < len(node):
                found.append(node[step])
            elif isinstance(step, str) and isinstance(node, dict) and step in node:
                found.append(node[step])
        nodes = found
    if WILDCARD in steps:
        return bool(nodes), nodes
    return bool(nodes), nodes[0] if nodes else None


def loads(text: str):
    """Parse JSON text, raising ValueError when it is not valid."""
    return json.loads(text)
