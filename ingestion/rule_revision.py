"""Apply sourced changes to an exact seasonal binding, preserving its base.

A hotfix is a data revision, not permission to promote or to invent missing
handlers. Each replacement is anchored to the SHA of the previous subtree.
"""

from copy import deepcopy
import hashlib
from urllib.parse import urlparse

from ingestion.knowledge_release import canonical
from trainer.simulation.state import UnsupportedRule


def checksum(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def reconcile(bindings, revision):
    if (
        revision.get("schema_version") != 1
        or revision.get("kind") != "candidate_rule_revision"
        or revision.get("runtime_promoted") is not False
        or revision.get("base_bindings_sha256") != checksum(bindings)
        or revision.get("base_patch") != bindings["patch"]
        or revision.get("set_key") != bindings["set_key"]
        or revision.get("release_sha256") != bindings["release_sha256"]
        or not isinstance(revision.get("patch"), str)
        or not revision["patch"]
    ):
        raise UnsupportedRule("revision does not match its sealed base")
    pending = revision.get("pending_reconciliation")
    status = revision.get("reconciliation_status")
    if (
        status not in ("partial", "complete")
        or not isinstance(pending, list)
        or any(not isinstance(value, str) or not value for value in pending)
        or (status == "complete" and pending)
    ):
        raise UnsupportedRule(
            "revision requires explicit reconciliation status and gaps"
        )
    changes = revision.get("changes")
    if not isinstance(changes, list) or not changes:
        raise UnsupportedRule("revision requires explicit changes")
    result = deepcopy(bindings)
    paths = []
    for change in changes:
        if set(change) != {
            "path",
            "expected_sha256",
            "value",
            "source_url",
            "source_section",
        }:
            raise UnsupportedRule("revision change needs complete provenance")
        path = change["path"]
        if (
            not isinstance(path, list)
            or len(path) < 2
            or path[0] not in ("champions", "traits", "items", "profile")
            or any(not isinstance(p, str) or not p for p in path)
        ):
            raise UnsupportedRule("invalid revision path")
        if any(path[: len(p)] == p or p[: len(path)] == path for p in paths):
            raise UnsupportedRule("overlapping revision changes")
        paths.append(path)
        source = urlparse(change["source_url"])
        if (
            source.scheme != "https"
            or not source.netloc
            or not change["source_section"]
        ):
            raise UnsupportedRule("revision source unavailable")
        parent = result
        for key in path[:-1]:
            if not isinstance(parent, dict) or key not in parent:
                raise UnsupportedRule("revision parent missing")
            parent = parent[key]
        if not isinstance(parent, dict):
            raise UnsupportedRule("revision parent must be an object")
        old = {"present": path[-1] in parent, "value": parent.get(path[-1])}
        if checksum(old) != change["expected_sha256"]:
            raise UnsupportedRule("revision base value changed")
        parent[path[-1]] = deepcopy(change["value"])
    # These fields always describe the base that the compiler checks. The
    # effective patch is attached only after successful compilation below.
    return result


def compile_revision(manifest, catalogs, bindings, revision):
    from training.compile_effects import compile_catalog

    effective = reconcile(bindings, revision)
    result = compile_catalog(manifest, catalogs, effective)
    result["catalog_patch"] = result["patch"]
    result["patch"] = revision["patch"]
    result["bindings_sha256"] = checksum({"base": bindings, "revision": revision})
    result["rule_revision"] = {
        "sha256": checksum(revision),
        "base_bindings_sha256": checksum(bindings),
        "effective_bindings_sha256": checksum(effective),
        "base_patch": bindings["patch"],
        "patch": revision["patch"],
        "changed_paths": [c["path"] for c in revision["changes"]],
        "disabled_content": deepcopy(revision.get("disabled_content", [])),
        "pending_reconciliation": deepcopy(revision.get("pending_reconciliation", [])),
        "reconciliation_status": revision["reconciliation_status"],
    }
    result["coverage"]["revision_reconciliation_complete"] = (
        revision["reconciliation_status"] == "complete"
    )
    # Historical limitations are retained as base provenance, not presented as
    # contradictory claims about the new revision (e.g. "excludes 18.3B").
    result["rule_revision"]["base_unresolved"] = deepcopy(
        result["coverage"]["unresolved"]
    )
    result["coverage"]["unresolved"] = [
        "Revision targets "
        + revision["patch"]
        + "; patch parity is "
        + revision["reconciliation_status"]
        + ".",
        "Candidate effects, mana roles and timings still require independent replay validation.",
        "The sealed base's unresolved rules remain applicable except explicitly changed paths; see rule_revision.base_unresolved.",
    ] + deepcopy(revision["pending_reconciliation"])
    return result
