"""Versioned round order, independent of champions and seasonal reward tables.

A calendar classifies boundaries. It does not silently settle combat, generate
loot, choose an augment or resolve carousel ownership.
"""

from copy import deepcopy
from .state import IllegalAction, UnsupportedRule


def describe(key, rules):
    if not isinstance(key, str) or key not in rules.get("rounds", {}):
        raise UnsupportedRule("round absent from explicit calendar")
    row = rules["rounds"][key]
    if row.get("kind") not in ("pvp", "pve", "carousel"):
        raise UnsupportedRule("unknown round kind")
    return dict(key=key, **deepcopy(row))


def successor(key, rules):
    describe(key, rules)
    keys = list(rules["rounds"])
    i = keys.index(key) + 1
    if i == len(keys):
        raise UnsupportedRule("calendar exhausted; no extrapolated rounds")
    return keys[i]


def require_next(previous, following, rules):
    if successor(previous, rules) != following:
        raise IllegalAction("round skipped, repeated or out of order")
    return describe(following, rules)
