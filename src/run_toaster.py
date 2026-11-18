"""Stage 0 deterministic proof. No API calls, no cost.

Loads the annotated example-toaster model, produces its TMF catalog entry via
the reference mapper, then maps a YANG instance to a TMF Service and back, and
asserts the round-trip returns the original (the faithfulness check).

Run:
    cd onsen-cognitive-reconciliation
    python3 src/run_toaster.py
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import reference_mapper as rm  # noqa: E402

YANG_DIR = os.path.join(ROOT, "models", "yang")


def main() -> int:
    ctx = rm.load_context(YANG_DIR)
    rm.add_module(ctx, os.path.join(YANG_DIR, "ietf-yang-tmf-map.yang"))
    toaster = rm.add_module(ctx, os.path.join(YANG_DIR, "example-toaster.yang"))
    ctx.validate()
    errors = [e for e in ctx.errors if e[1] not in ("UNUSED_IMPORT",)]
    if errors:
        for pos, tag, args in ctx.errors:
            print(f"  pyang: {tag} at {pos}: {args}")

    print("=" * 68)
    print("TMF catalog (ServiceSpecification) from example-toaster")
    print("=" * 68)
    catalog = rm.map_schema_to_catalog(toaster)
    print(json.dumps(catalog, indent=2))

    with open(os.path.join(ROOT, "fixtures", "toaster-instance.json")) as fh:
        instance = json.load(fh)

    print("\n" + "=" * 68)
    print("YANG instance -> TMF Service instance")
    print("=" * 68)
    services = rm.map_instance_to_tmf(toaster, instance)
    print(json.dumps(services, indent=2))

    print("\n" + "=" * 68)
    print("TMF Service instance -> YANG instance (reverse)")
    print("=" * 68)
    back = rm.map_tmf_to_instance(toaster, services)
    print(json.dumps(back, indent=2))

    print("\n" + "=" * 68)
    print("Faithfulness round-trip check")
    print("=" * 68)
    ok = back == instance
    print("PASS" if ok else "FAIL")
    if not ok:
        print("  original:", json.dumps(instance, sort_keys=True))
        print("  returned:", json.dumps(back, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
