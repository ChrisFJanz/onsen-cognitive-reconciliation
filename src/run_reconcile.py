"""Stage 1 entry point: run the agent-to-agent reconciliation, then score the
translator it emits.

Examples:
    cd ~/Downloads/onsen-reconciliation-demonstrator

    # Plumbing check, no key, no cost (also proves interrupt/resume):
    python3 src/run_reconcile.py --provider mock --run-id toaster-mock

    # Real run on your OpenAI licence (key + model from .env):
    python3 src/run_reconcile.py --provider openai --run-id toaster-live

    # Resume an interrupted run (replays saved steps, 0 API calls, continues):
    python3 src/run_reconcile.py --provider openai --run-id toaster-live --resume

Scores:
  faithfulness : YANG instance -> TMF -> YANG instance returns the original.
  equivalence  : the emitted translator's TMF output matches the rule-derived
                 reference mapper (instance level in this stage).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import reference_mapper as rm       # noqa: E402
import translator                   # noqa: E402
from lexicon import yang_lexicon    # noqa: E402
from reconcile import Negotiator    # noqa: E402

YANG_DIR = os.path.join(ROOT, "models", "yang")


def build_identity_table(module) -> dict:
    """A correct mapping table derived straight from the module, used as the
    MockProvider's canned 'agent' reply so the pipeline runs with no key."""
    roots = rm._find_annotated_roots(module)
    root_stmt, ann = roots[0]
    chars = []
    for child in rm._data_children(root_stmt):
        if child.keyword in ("leaf", "leaf-list"):
            t = child.search_one("type")
            jtype = rm.jsonschema_type(t)
            if child.keyword == "leaf-list":
                jtype = rm._array_type(jtype)
            chars.append({"yang_name": child.arg, "tmf_name": child.arg,
                          "json_type": jtype})
    return {
        "root": {"yang_module": module.arg, "yang_path": root_stmt.arg,
                 "tmf_type": "ServiceSpecification", "tmf_name": ann[1]},
        "characteristics": chars,
    }


def make_provider(kind: str, module, model=None):
    if kind == "mock":
        from providers import MockProvider
        table_json = json.dumps(build_identity_table(module))
        return MockProvider({"propose": table_json, "review": table_json})
    if kind == "openai":
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(ROOT, ".env"))
        except Exception:
            pass
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit("OPENAI_API_KEY not set. Write it into .env first "
                             "(see README), then re-run.")
        from providers import OpenAIProvider
        return OpenAIProvider(model)
    raise SystemExit(f"unknown provider: {kind}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["mock", "openai"], default="mock")
    ap.add_argument("--run-id", default="toaster")
    ap.add_argument("--schema", default=os.path.join(YANG_DIR, "example-toaster.yang"))
    ap.add_argument("--instance", default=os.path.join(ROOT, "fixtures", "toaster-instance.json"))
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--model", default=None,
                    help="exact OpenAI model id; overrides OPENAI_MODEL in .env")
    ap.add_argument("--transcripts", default=os.path.join(ROOT, "transcripts"))
    args = ap.parse_args()

    ctx = rm.load_context(YANG_DIR)
    rm.add_module(ctx, os.path.join(YANG_DIR, "ietf-yang-tmf-map.yang"))
    module = rm.add_module(ctx, args.schema)
    ctx.validate()

    lex = yang_lexicon(module)
    provider = make_provider(args.provider, module, args.model)

    print(f"[run] provider={args.provider} model={provider.model} "
          f"run-id={args.run_id} resume={args.resume}")
    neg = Negotiator(provider, args.run_id, args.transcripts)
    try:
        table = neg.run(lex, module.arg, resume=args.resume)
    except KeyboardInterrupt:
        print("\n[interrupted] progress saved. Re-run with --resume to continue.")
        return 130

    out_dir = os.path.join(ROOT, "out")
    os.makedirs(out_dir, exist_ok=True)
    table_path = os.path.join(out_dir, f"{args.run_id}-table.json")
    with open(table_path, "w") as fh:
        json.dump(table, fh, indent=2)

    with open(args.instance) as fh:
        instance = json.load(fh)

    services = translator.map_instance_to_tmf(table, instance)
    back = translator.map_tmf_to_instance(table, services)
    reference = rm.map_instance_to_tmf(module, instance)

    faithful = back == instance
    equivalent = services == reference

    def char_names(svcs):
        names = []
        for s in svcs:
            names.extend(c["name"] for c in s.get("serviceCharacteristic", []))
        return names

    agent_names = char_names(services)
    oracle_names = char_names(reference)
    name_mismatches = [
        {"oracle": o, "agent": a}
        for o, a in zip(oracle_names, agent_names) if o != a
    ]

    result = {
        "run_id": args.run_id,
        "provider": args.provider,
        "model": provider.model,
        "metrics": {
            "api_calls_this_run": neg.api_calls,
            "seconds_this_run": round(neg.tot_seconds, 1),
            "prompt_tokens": neg.tot_prompt,
            "completion_tokens": neg.tot_completion,
        },
        "faithfulness_roundtrip": "PASS" if faithful else "FAIL",
        "equivalence_vs_oracle": "PASS" if equivalent else "FAIL",
        "name_mismatches": name_mismatches,
        "agent_services": services,
        "oracle_services": reference,
        "negotiated_table": table,
    }
    result_path = os.path.join(out_dir, f"{args.run_id}-result.json")
    with open(result_path, "w") as fh:
        json.dump(result, fh, indent=2)

    print("\n" + "=" * 60)
    print(f"negotiated translator: {table_path}")
    print(neg.summary())
    print("-" * 60)
    print(f"faithfulness round-trip : {'PASS' if faithful else 'FAIL'}")
    print(f"equivalence vs oracle   : {'PASS' if equivalent else 'FAIL'}")
    print("=" * 60)
    print(f"\nresult written: {result_path}")
    print("Drag that one file into the chat; it carries the scores and diff.")
    return 0 if (faithful and equivalent) else 1


if __name__ == "__main__":
    raise SystemExit(main())
