"""Nested instance-data mapping: YANG instance <-> TMF Service instance.

This is the operational-concrete half. The schema mapping says how models line
up; this shows a real instance of a service flowing from a YANG datastore to a
TMF Service and back without loss, through the reconciled mapping.

Following draft-lls-onsen-yang-tmf-mapping, a Service carries the annotated
root's own leaves as serviceCharacteristic, and every nested container or list
instance becomes one Feature in a flat collection, named by its path (list
entries carry a [key='value'] predicate), linked to its parent by a composedOf
featureRelationship, with that node's leaves as featureCharacteristic.

The mapping is deterministic. Characteristic names are the YANG identifiers
verbatim, which is the reconciled naming anchor, so the transform shown here is
the translator the agents converge on, exercised on real data.
"""

from __future__ import annotations

import re
from typing import Any

import reference_mapper as rm


def _leaves(stmt):
    return [c for c in rm._data_children(stmt) if c.keyword in ("leaf", "leaf-list")]


def _first_key(list_stmt):
    k = list_stmt.search_one("key")
    return k.arg.split()[0] if k is not None else None


# --------------------------------------------------------------------------
# Forward: YANG instance entry -> TMF Service
# --------------------------------------------------------------------------

def _emit(stmt, entry, path, parent, feats):
    chars = [{"name": c.arg, "value": entry[c.arg]}
             for c in _leaves(stmt) if c.arg in entry]
    feat: dict[str, Any] = {"name": path, "featureCharacteristic": chars}
    feat["featureRelationship"] = [
        {"relationshipType": "composedOf", "name": parent}]
    feats.append(feat)
    _descend(stmt, entry, path, feats)


def _descend(stmt, entry, path, feats):
    for c in rm._data_children(stmt):
        if c.arg not in entry:
            continue
        if c.keyword == "container":
            cpath = f"{path}/{c.arg}" if path else c.arg
            _emit(c, entry[c.arg], cpath, path, feats)
        elif c.keyword == "list":
            key = _first_key(c)
            for item in entry[c.arg]:
                seg = f"{c.arg}[{key}='{item.get(key)}']"
                cpath = f"{path}/{seg}" if path else seg
                _emit(c, item, cpath, path, feats)


def entry_to_service(root_stmt, cfs_name, entry) -> dict:
    svc_chars = [{"name": c.arg, "value": entry[c.arg]}
                 for c in _leaves(root_stmt) if c.arg in entry]
    feats: list[dict] = []
    _descend(root_stmt, entry, "", feats)
    for f in feats:
        for rel in f.get("featureRelationship", []):
            if rel["name"] == "":
                rel["name"] = cfs_name
    return {
        "@type": "Service",
        "serviceSpecification": {"name": cfs_name},
        "serviceCharacteristic": svc_chars,
        "feature": feats,
    }


def datastore_to_tmf(module, root_stmt, cfs_name, instance) -> list[dict]:
    key = f"{module.arg}:{root_stmt.arg}"
    data = instance.get(key, instance.get(root_stmt.arg))
    if data is None:
        return []
    entries = data if isinstance(data, list) else [data]
    return [entry_to_service(root_stmt, cfs_name, e) for e in entries]


# --------------------------------------------------------------------------
# Reverse: TMF Service -> YANG instance entry
# --------------------------------------------------------------------------

_SEG = re.compile(r"^([^\[]+)(?:\[([^=]+)='(.*)'\])?$")


def _parse_path(name: str):
    segs = []
    for raw in name.split("/"):
        m = _SEG.match(raw)
        segs.append((m.group(1), m.group(2), m.group(3)))
    return segs


def service_to_entry(service: dict) -> dict:
    entry: dict[str, Any] = {}
    for ch in service.get("serviceCharacteristic", []):
        entry[ch["name"]] = ch["value"]
    for feat in service.get("feature", []):
        cur = entry
        for name, kname, kval in _parse_path(feat["name"]):
            if kname is None:
                cur = cur.setdefault(name, {})
            else:
                lst = cur.setdefault(name, [])
                item = next((x for x in lst if str(x.get(kname)) == kval), None)
                if item is None:
                    item = {kname: kval}
                    lst.append(item)
                cur = item
        for ch in feat.get("featureCharacteristic", []):
            cur[ch["name"]] = ch["value"]
    return entry


def tmf_to_datastore(module, root_stmt, services) -> dict:
    return {f"{module.arg}:{root_stmt.arg}":
            [service_to_entry(s) for s in services]}
