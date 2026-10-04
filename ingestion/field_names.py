"""Recover catalog field names from placeholders without inferring mechanics.

The spelling is evidence only when its case-insensitive FNV-1a hash matches
the stored key. A match does not establish scaling, timing or patch validity.
"""

import re

from trainer.simulation.state import UnsupportedRule

PLACEHOLDER = re.compile(r"@([A-Za-z_][A-Za-z_0-9]*)(?:[^@]*)@")


def field_hash(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
        raise UnsupportedRule("invalid numeric field name")
    value = 2166136261
    for byte in name.lower().encode("ascii"):
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return "{" + format(value, "08x") + "}"


def resolve_fields(description, fields):
    """Return unique placeholder matches; never resolve an ambiguous hash."""
    names = {}
    for match in PLACEHOLDER.finditer(description):
        name = match.group(1)
        names.setdefault(name.lower(), name)
    candidates = {}
    for normalized, name in names.items():
        candidates.setdefault(field_hash(name), {})[normalized] = name
    resolved = {}
    for key in fields:
        if re.fullmatch(r"\{[0-9a-f]{8}\}", key):
            matches = candidates.get(key, {})
            if len(matches) > 1:
                raise UnsupportedRule("ambiguous catalog field hash")
            if matches:
                resolved[key] = next(iter(matches.values()))
        elif key.lower() in names:
            resolved[key] = names[key.lower()]
    return resolved
