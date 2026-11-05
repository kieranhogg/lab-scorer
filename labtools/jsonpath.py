"""A small JSONPath subset for lab checks, so no extra dependency is needed.

Supported: $, .key, ['key'], ["key"], [0], [-1], [*] and .*
"""
import re
from typing import Any

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


def _child(node: object, step: object) -> list:
    """Return the one child of node at step as a list, empty when node has no such child."""
    if isinstance(node, list) and isinstance(step, int):
        return [node[step]] if -len(node) <= step < len(node) else []
    if isinstance(node, dict) and isinstance(step, str):
        return [node[step]] if step in node else []
    return []


def lookup(data, path: str) -> tuple[bool, Any]:
    """Return (found, value). A path with a wildcard gives the list of every match."""
    steps = parse(path)
    nodes = [data]
    for step in steps:
        found = []
        for node in nodes:
            if step is WILDCARD:
                found += list(node.values()) if isinstance(node, dict) else list(node) if isinstance(node, list) else []
            else:
                found += _child(node, step)
        nodes = found
    if WILDCARD in steps:
        return bool(nodes), nodes
    return bool(nodes), nodes[0] if nodes else None
