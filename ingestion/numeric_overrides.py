"""Apply reviewed patch deltas to a copy of sealed numeric catalog data."""

from copy import deepcopy
import math
from urllib.parse import urlparse

from trainer.simulation.state import UnsupportedRule


def apply_overrides(fields, changes, patch):
    result = deepcopy(fields)
    seen = set()
    for change in changes:
        if set(change) != {
            "field",
            "expected",
            "value",
            "patch",
            "source_url",
            "source_section",
        }:
            raise UnsupportedRule("incomplete numeric override provenance")
        key = change["field"]
        if key in seen or key not in fields:
            raise UnsupportedRule("duplicate or missing override field")
        seen.add(key)
        if not patch or change["patch"] != patch:
            raise UnsupportedRule("numeric override belongs to another patch")
        url = urlparse(change["source_url"])
        if url.scheme != "https" or not url.netloc or not change["source_section"]:
            raise UnsupportedRule("numeric override needs a source and section")
        for number in (fields[key], change["expected"], change["value"]):
            if type(number) not in (int, float) or not math.isfinite(number):
                raise UnsupportedRule("invalid numeric override value")
        if not math.isclose(fields[key], change["expected"], rel_tol=0, abs_tol=1e-6):
            raise UnsupportedRule("numeric override base has changed; review required")
        result[key] = change["value"]
    return result
