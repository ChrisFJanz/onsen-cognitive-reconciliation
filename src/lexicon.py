"""Deterministic reference-lexicon derivation.

Per draft-janz-nmrg-reference-lexicons, each system brings a thin lexicon
derived from its own model: a consultable nomenclature of named entities with
disambiguating definitions. Here the YANG-side lexicon is derived directly from
the annotated YANG module. No inference is used to build it.

A lexicon entry is:
  { "term": <node name>, "path": <path from root>, "kind": container|list|leaf|
    leaf-list, "definition": <description text>, "datatype": <yang base type> }
"""

from __future__ import annotations

from typing import Any

import reference_mapper as rm


def yang_lexicon(module) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    def describe(stmt) -> str:
        d = stmt.search_one("description")
        return d.arg.strip() if d is not None and d.arg else ""

    def rec(stmt, path):
        for child in rm._data_children(stmt):
            if rm.tmf_annotation(child) == ("ignore", None):
                continue
            cpath = f"{path}/{child.arg}" if path else child.arg
            entry: dict[str, Any] = {
                "term": child.arg,
                "path": cpath,
                "kind": child.keyword,
                "definition": describe(child),
            }
            if child.keyword in ("leaf", "leaf-list"):
                t = child.search_one("type")
                entry["datatype"] = rm._base_type_name(t)
            entries.append(entry)
            if child.keyword in ("container", "list"):
                rec(child, cpath)

    for root in rm._data_children(module):
        cpath = root.arg
        entries.append({
            "term": root.arg,
            "path": cpath,
            "kind": root.keyword,
            "definition": describe(root),
        })
        rec(root, cpath)
    return entries
