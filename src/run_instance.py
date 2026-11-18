"""Operational-concrete demonstration: a real L3SM instance, YANG to TMF to YANG.

Maps a vpn-service instance to a TMF Service (nested features, composedOf), maps
it back, and checks the round-trip returns the original. No API, no cost.

Run:
    cd ~/Downloads/onsen-reconciliation-demonstrator
    .venv/bin/python src/run_instance.py
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import reference_mapper as rm        # noqa: E402
import instance_mapper as im         # noqa: E402

YANG_DIR = os.path.join(ROOT, "models", "yang")


def main() -> int:
    ctx = rm.load_context(YANG_DIR)
    rm.add_module(ctx, os.path.join(YANG_DIR, "ietf-yang-tmf-map.yang"))
    module = rm.add_module(ctx, os.path.join(YANG_DIR, "ietf-l3vpn-svc.yang"))
    ctx.validate()

    # The vpn-service root.
    root, cfs = None, None
    for stmt, ann in rm._find_annotated_roots(module):
        if stmt.arg == "vpn-service":
            root, cfs = stmt, ann[1]
    if root is None:
        raise SystemExit("vpn-service root not found")

    with open(os.path.join(ROOT, "fixtures", "l3sm-vpn-service-instance.json")) as fh:
        instance = json.load(fh)

    services = im.datastore_to_tmf(module, root, cfs, instance)
    back = im.tmf_to_datastore(module, root, services)
    faithful = back == instance

    print("=" * 64)
    print("L3SM vpn-service instance  ->  TMF Service (nested features)")
    print("=" * 64)
    print(json.dumps(services, indent=2))
    print("\n" + "=" * 64)
    print("features emitted:", len(services[0]["feature"]))
    print("faithfulness round-trip (YANG -> TMF -> YANG):",
          "PASS" if faithful else "FAIL")
    print("=" * 64)
    if not faithful:
        print("original:", json.dumps(instance, sort_keys=True))
        print("returned:", json.dumps(back, sort_keys=True))

    out_dir = os.path.join(ROOT, "out")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "l3sm-instance-result.json"), "w") as fh:
        json.dump({"faithfulness_roundtrip": "PASS" if faithful else "FAIL",
                   "features": len(services[0]["feature"]),
                   "tmf_service": services}, fh, indent=2)
    return 0 if faithful else 1


if __name__ == "__main__":
    raise SystemExit(main())
