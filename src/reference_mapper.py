"""Deterministic YANG -> TMF reference mapper.

Implements the normative mapping rules of draft-lls-onsen-yang-tmf-mapping-00
(sections 2 to 4). This module is the *oracle* for the demonstrator: it encodes
"what the standard would produce" so that the output of the agent-to-agent
reconciliation can be scored against it. It performs no inference and makes no
network calls.

Two directions are supported:
  * schema  : a YANG module -> a TMF633/634 ServiceSpecification catalog entry
  * instance: YANG instance data <-> TMF640/641 Service instance data

Scope note: the schema mapping runs YANG -> TMF only, as the draft specifies.
Instance data is mapped both ways, which is what the faithfulness round-trip
check relies on.
"""

from __future__ import annotations

import copy
from typing import Any

from pyang import context, repository, statements

TMF_EXTENSIONS = {"cfs-service", "rfs-service", "resource", "ignore"}

# YANG built-in type -> JSON Schema type (draft section 4, and leaf mapping).
_SCALAR_JSON_TYPE = {
    "boolean": "boolean",
    "string": "string",
    "decimal64": "number",
    "enumeration": "string",
    "identityref": "string",
    # The draft's section 4 type table does not cover YANG 'empty'. The first
    # live L3SM run surfaced this: on 'permit-any' all 20 trials chose boolean
    # (presence as true/false), the better representation, while this oracle had
    # defaulted it to string. Corrected to the agents' unanimous choice.
    "empty": "boolean",
}
_INTEGER_TYPES = {
    "int8", "int16", "int32", "int64",
    "uint8", "uint16", "uint32", "uint64",
}


def load_context(search_path: str) -> context.Context:
    repo = repository.FileRepository(search_path)
    return context.Context(repo)


def add_module(ctx: context.Context, filename: str) -> statements.Statement:
    with open(filename) as fh:
        text = fh.read()
    module = ctx.add_module(filename, text)
    return module


# ---------------------------------------------------------------------------
# Annotation and type helpers
# ---------------------------------------------------------------------------

def tmf_annotation(stmt: statements.Statement) -> tuple[str, str | None] | None:
    """Return (kind, name) for a tmf: annotation on stmt, else None."""
    for sub in stmt.substmts:
        kw = sub.keyword
        name = kw[1] if isinstance(kw, tuple) else kw
        if name in TMF_EXTENSIONS:
            return (name, sub.arg)
    return None


def _base_type_name(type_stmt: statements.Statement) -> str:
    """Resolve to a YANG built-in base type name where possible."""
    t = type_stmt
    # Walk typedefs to the base built-in type.
    seen = 0
    while getattr(t, "i_typedef", None) is not None and seen < 32:
        t = t.i_typedef.search_one("type")
        seen += 1
    return t.arg


def jsonschema_type(type_stmt: statements.Statement) -> str:
    base = _base_type_name(type_stmt)
    if base in _INTEGER_TYPES:
        return "integer"
    return _SCALAR_JSON_TYPE.get(base, "string")


def _array_type(scalar_json_type: str) -> str:
    return {
        "boolean": "booleanArray",
        "string": "stringArray",
        "integer": "integerArray",
        "number": "numberArray",
    }.get(scalar_json_type, "stringArray")


def _value_specs(type_stmt: statements.Statement, default_stmt) -> list[dict]:
    """range/length -> CharacteristicValueSpecification entries;
    each enum -> a CharacteristicValueSpecification; default -> isDefault."""
    specs: list[dict] = []
    rng = type_stmt.search_one("range")
    if rng is not None:
        specs.append({"valueType": "range", "value": rng.arg})
    length = type_stmt.search_one("length")
    if length is not None:
        specs.append({"valueType": "length", "value": length.arg})
    for enum in type_stmt.search("enum"):
        specs.append({"valueType": "enumeration", "value": enum.arg})
    if default_stmt is not None:
        specs.append({"isDefault": True, "value": default_stmt.arg})
    return specs


def _characteristic(stmt: statements.Statement, is_leaf_list: bool) -> dict:
    type_stmt = stmt.search_one("type")
    scalar = jsonschema_type(type_stmt)
    char: dict[str, Any] = {
        "name": stmt.arg,
        "valueType": _array_type(scalar) if is_leaf_list else scalar,
    }
    pattern = type_stmt.search_one("pattern")
    if pattern is not None:
        char["regex"] = pattern.arg
    specs = _value_specs(type_stmt, stmt.search_one("default"))
    if specs:
        char["characteristicValueSpecification"] = specs
    # Cardinality (mandatory, min/max-elements). List keys handled by caller.
    if is_leaf_list:
        mn = stmt.search_one("min-elements")
        mx = stmt.search_one("max-elements")
        if mn is not None:
            char["minCardinality"] = int(mn.arg)
        if mx is not None:
            char["maxCardinality"] = int(mx.arg)
    else:
        mandatory = stmt.search_one("mandatory")
        char["minCardinality"] = 1 if (mandatory is not None and mandatory.arg == "true") else 0
    return char


def _data_children(stmt: statements.Statement) -> list[statements.Statement]:
    """Effective data children, descending transparently through choice/case.

    YANG choice and case nodes carry no data of their own; their leaves and
    containers are what map. pyang represents them as their own statements, so
    we expand them here and the rest of the mapper never sees a choice.
    """
    out: list[statements.Statement] = []
    for c in getattr(stmt, "i_children", []):
        if c.keyword in ("container", "list", "leaf", "leaf-list"):
            out.append(c)
        elif c.keyword in ("choice", "case"):
            out.extend(_data_children(c))
    return out


# ---------------------------------------------------------------------------
# Schema mapping: YANG module -> TMF catalog (ServiceSpecification)
# ---------------------------------------------------------------------------

def map_schema_to_catalog(module: statements.Statement) -> list[dict]:
    """Return the list of top-level TMF specifications produced from a module.

    Each annotated (cfs-service/rfs-service/resource) container or list at or
    below the mapping root becomes a Service/Resource specification; nested
    containers and lists become FeatureSpecifications linked composedOf; leaves
    and leaf-lists become characteristics.
    """
    specs: list[dict] = []
    for child in _data_children(module):
        _collect_specs(child, prefix="", out=specs)
    return specs


def _spec_kind(annotation) -> str:
    return {
        "cfs-service": "ServiceSpecification",
        "rfs-service": "ServiceSpecification",
        "resource": "ResourceSpecification",
    }.get(annotation[0], "ServiceSpecification")


def _collect_specs(stmt, prefix, out):
    ann = tmf_annotation(stmt)
    if ann is not None and ann[0] == "ignore":
        return
    if ann is not None and ann[0] in ("cfs-service", "rfs-service", "resource"):
        spec = {
            "name": ann[1],
            "@type": _spec_kind(ann),
            "serviceSpecCharacteristic": [],
            "featureSpecification": [],
        }
        _fill_features(stmt, root=stmt, spec=spec)
        out.append(spec)
    else:
        # Unannotated top-level node: recurse looking for annotated roots.
        for child in _data_children(stmt):
            _collect_specs(child, prefix, out)


def _feature_name(stmt, root) -> str:
    parts = []
    node = stmt
    while node is not None and node is not root:
        if node.keyword in ("container", "list"):
            parts.append(node.arg)
        node = getattr(node, "parent", None)
    return "/".join(reversed(parts))


def _list_key_and_unique(stmt) -> tuple[set[str], set[str]]:
    """Return (key leaf names, unique leaf names) for a list node."""
    keys: set[str] = set()
    uniques: set[str] = set()
    if stmt.keyword == "list":
        key = stmt.search_one("key")
        if key is not None:
            keys = set(key.arg.split())
        for uq in stmt.search("unique"):
            uniques.update(uq.arg.split())
    return keys, uniques


def _fill_features(stmt, root, spec):
    """Walk the subtree under an annotated root, filling characteristics
    (leaves/leaf-lists) and nested FeatureSpecifications (containers/lists)."""
    keys, uniques = _list_key_and_unique(stmt)
    for child in _data_children(stmt):
        if tmf_annotation(child) == ("ignore", None):
            continue
        if child.keyword in ("leaf", "leaf-list"):
            char = _characteristic(child, is_leaf_list=(child.keyword == "leaf-list"))
            if child.arg in keys:
                char["minCardinality"] = 1  # list keys are always mandatory
            if child.arg in uniques:
                char["isUnique"] = True
            if stmt is root:
                spec["serviceSpecCharacteristic"].append(char)
            else:
                _feature_for(stmt, root, spec)["featureSpecCharacteristic"].append(char)
        elif child.keyword in ("container", "list"):
            feat = _feature_for(child, root, spec)
            # composedOf relationship from parent to this feature.
            parent_name = None if stmt is root else _feature_name(stmt, root)
            feat.setdefault("featureSpecRelationship", [])
            if parent_name is not None:
                feat["featureSpecRelationship"].append(
                    {"relationshipType": "composedOf", "name": parent_name})
            _fill_features(child, root, spec)


def _feature_for(stmt, root, spec):
    name = _feature_name(stmt, root)
    for f in spec["featureSpecification"]:
        if f["name"] == name:
            return f
    feat = {"name": name, "featureSpecCharacteristic": []}
    spec["featureSpecification"].append(feat)
    return feat


# ---------------------------------------------------------------------------
# Instance mapping: YANG instance data <-> TMF Service instance
# ---------------------------------------------------------------------------

def _find_annotated_roots(module):
    roots = []
    def rec(stmt):
        ann = tmf_annotation(stmt)
        if ann and ann[0] in ("cfs-service", "rfs-service", "resource"):
            roots.append((stmt, ann))
            return
        for c in _data_children(stmt):
            rec(c)
    for c in _data_children(module):
        rec(c)
    return roots


def map_instance_to_tmf(module, instance: dict) -> list[dict]:
    """Map RFC-7951-style YANG instance data to TMF Service instances.

    One TMF Service per instance of an annotated root list entry (or per
    annotated container).
    """
    services: list[dict] = []
    for root_stmt, ann in _find_annotated_roots(module):
        key = f"{module.arg}:{root_stmt.arg}"
        data = instance.get(key, instance.get(root_stmt.arg))
        if data is None:
            continue
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            services.append(_service_from_entry(root_stmt, ann, entry))
    return services


def _service_from_entry(root_stmt, ann, entry) -> dict:
    svc = {
        "@type": "Service",
        "serviceSpecification": {"name": ann[1]},
        "serviceCharacteristic": [],
    }
    for child in _data_children(root_stmt):
        if child.arg not in entry:
            continue
        if child.keyword in ("leaf", "leaf-list"):
            svc["serviceCharacteristic"].append(
                {"name": child.arg, "value": entry[child.arg]})
    return svc


def map_tmf_to_instance(module, services: list[dict]) -> dict:
    """Reverse: TMF Service instances -> RFC-7951-style YANG instance data."""
    out: dict[str, list] = {}
    roots = {ann[1]: (stmt, ann) for stmt, ann in _find_annotated_roots(module)}
    for svc in services:
        spec_name = svc.get("serviceSpecification", {}).get("name")
        if spec_name not in roots:
            continue
        root_stmt, _ = roots[spec_name]
        entry: dict[str, Any] = {}
        child_types = {c.arg: c.keyword for c in _data_children(root_stmt)}
        for ch in svc.get("serviceCharacteristic", []):
            entry[ch["name"]] = ch["value"]
        key = f"{module.arg}:{root_stmt.arg}"
        out.setdefault(key, []).append(entry)
    return out
