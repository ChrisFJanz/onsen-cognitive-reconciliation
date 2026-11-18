"""Deterministic translator executor.

Consumes the mapping table emitted by the reconciliation (the agents negotiate
once; the table they produce is applied deterministically thereafter, with no
further inference). Mirrors the instance-level mapping of the reference mapper,
but is driven entirely by the negotiated table rather than by the draft's rules.
That separation is the point: if the table-driven output matches the
rule-driven reference output, the agents reached the standard on their own.

Mapping table shape:
  {
    "root": {"yang_module": "example-toaster", "yang_path": "toaster",
             "tmf_type": "ServiceSpecification", "tmf_name": "Toaster"},
    "characteristics": [
      {"yang_name": "serial-number", "tmf_name": "serial-number",
       "json_type": "string"}, ...
    ]
  }
"""

from __future__ import annotations

from typing import Any


def _root(table) -> dict:
    return table["root"]


def map_instance_to_tmf(table: dict, instance: dict) -> list[dict]:
    root = _root(table)
    key = f"{root['yang_module']}:{root['yang_path']}"
    data = instance.get(key, instance.get(root["yang_path"]))
    if data is None:
        return []
    entries = data if isinstance(data, list) else [data]
    y2t = {c["yang_name"]: c["tmf_name"] for c in table["characteristics"]}
    services = []
    for entry in entries:
        chars = []
        for yname, value in entry.items():
            if yname in y2t:
                chars.append({"name": y2t[yname], "value": value})
        services.append({
            "@type": "Service",
            "serviceSpecification": {"name": root["tmf_name"]},
            "serviceCharacteristic": chars,
        })
    return services


def map_tmf_to_instance(table: dict, services: list[dict]) -> dict:
    root = _root(table)
    t2y = {c["tmf_name"]: c["yang_name"] for c in table["characteristics"]}
    key = f"{root['yang_module']}:{root['yang_path']}"
    out: dict[str, list] = {}
    for svc in services:
        if svc.get("serviceSpecification", {}).get("name") != root["tmf_name"]:
            continue
        entry: dict[str, Any] = {}
        for ch in svc.get("serviceCharacteristic", []):
            if ch["name"] in t2y:
                entry[t2y[ch["name"]]] = ch["value"]
        out.setdefault(key, []).append(entry)
    return out
