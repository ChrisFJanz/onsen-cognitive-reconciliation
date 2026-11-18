"""Stage 2b: ad hoc reconciliation on the BASIC, unannotated L3SM model.

The annotated run leans on draft-lls-onsen-yang-tmf-mapping: its tmf: annotations
already say which node is a TMF service. This run removes that crutch. The agents
are given the plain RFC 8299 model and must (1) locate the service roots
themselves, then (2) reconcile each subtree, with no prior mapping to lean on.

Because there is no agreed mapping, equivalence to a draft is not the measure.
The measures are:
  * faithfulness      : a real instance round-trips through the emitted mapping.
  * root agreement    : across independent trials, do the agents choose the same
                        service roots?
  * mapping agreement : among trials that agree on roots, do they produce the same
                        characteristic names and types?

This is the standard-free pole, the counterpart to the annotated (configuration)
pole.

Run:
    cd ~/Downloads/onsen-reconciliation-demonstrator
    # plumbing, no key, no cost:
    caffeinate -is .venv/bin/python src/reconcile_l3sm_basic.py --provider mock --run-id basic-mock --trials 2
    # live:
    caffeinate -is .venv/bin/python src/reconcile_l3sm_basic.py --provider openai --run-id basic-live --trials 10
    # resume:
    caffeinate -is .venv/bin/python src/reconcile_l3sm_basic.py --provider openai --run-id basic-live --trials 10 --resume
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import reference_mapper as rm       # noqa: E402
import reconcile_l3sm as base       # noqa: E402
from providers import estimate_cost  # noqa: E402

YANG_DIR = os.path.join(ROOT, "models", "yang")

LOCATE_SYS = (
    "You are a cognitive agent reconciling a YANG model to a TM Forum "
    "representation with no prior mapping. From the model's structure, decide "
    "which container or list nodes are the customer-facing services that should "
    "each become a TMF ServiceSpecification. Return JSON "
    "{\"service_roots\": [\"<path>\", ...]} using the exact paths given. "
    "Respond with JSON only."
)


def load_plain(schema_path):
    ctx = rm.load_context(YANG_DIR)
    module = rm.add_module(ctx, schema_path)
    ctx.validate()
    return module


def top_container(module):
    for c in rm._data_children(module):
        if c.keyword == "container":
            return c
    return rm._data_children(module)[0]


def candidates(top):
    """container/list nodes under the top container, to depth 3, as the
    structure the agent reasons over."""
    out = []

    def walk(stmt, prefix, depth):
        for c in rm._data_children(stmt):
            if c.keyword in ("container", "list"):
                path = f"{prefix}/{c.arg}" if prefix else c.arg
                d = c.search_one("description")
                out.append({"path": path, "kind": c.keyword,
                            "desc": (d.arg.strip().split("\n")[0] if d and d.arg else "")})
                if depth < 3:
                    walk(c, path, depth + 1)

    walk(top, "", 1)
    return out


def resolve(top, path):
    node = top
    for part in path.split("/"):
        nxt = None
        for c in rm._data_children(node):
            if c.arg == part and c.keyword in ("container", "list"):
                nxt = c
                break
        if nxt is None:
            return None
        node = nxt
    return node


class BasicMock:
    """Perfect-agent mock: locates vpn-service and site, maps verbatim."""
    model = "mock"

    def complete(self, step, system, user):
        from providers import LLMResult
        if "CANDIDATES:" in user:
            text = json.dumps({"service_roots": ["vpn-services/vpn-service", "sites/site"]})
        else:
            start = user.index("LEAVES:") + len("LEAVES:")
            leaves, _ = json.JSONDecoder().raw_decode(user[start:])
            chars = []
            for lx in leaves:
                yt = lx["yang_type"]
                jt = ("integer" if yt in rm._INTEGER_TYPES
                      else rm._SCALAR_JSON_TYPE.get(yt, "string"))
                if lx["kind"] == "leaf-list":
                    jt = rm._array_type(jt)
                chars.append({"yang_name": lx["yang_name"],
                              "tmf_name": lx["yang_name"], "json_type": jt})
            text = json.dumps({"characteristics": chars})
        return LLMResult(text, len(user) // 4, len(text) // 4, 0.0, self.model)


def make_provider(kind, model=None):
    if kind == "mock":
        return BasicMock()
    return base.make_provider("openai", model)


def locate_prompt(cands):
    lines = "\n".join(f"  {c['path']}  [{c['kind']}]  {c['desc']}" for c in cands)
    return ("From this model structure, choose the service roots.\nCANDIDATES:\n"
            + lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["mock", "openai"], default="mock")
    ap.add_argument("--run-id", default="basic")
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--model", default=None)
    ap.add_argument("--schema", default=os.path.join(YANG_DIR, "ietf-l3vpn-svc-basic.yang"))
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    module = load_plain(args.schema)
    top = top_container(module)
    cands = candidates(top)
    provider = make_provider(args.provider, args.model)

    print(f"[run] provider={args.provider} model={provider.model} "
          f"run-id={args.run_id} trials={args.trials}")
    print(f"[model] basic (unannotated) L3SM: {len(cands)} candidate container/list "
          f"nodes; agents must locate the service roots themselves")

    ckpt = base.Checkpoint(os.path.join(ROOT, "transcripts", f"{args.run_id}.jsonl"))
    if args.resume:
        ckpt.load()
    totals = {"calls": 0, "seconds": 0.0, "pt": 0, "ct": 0}

    def call(key, system, user):
        if key in ckpt.done:
            return ckpt.done[key]["text"]
        res = provider.complete(key, system, user)
        totals["calls"] += 1
        totals["seconds"] += res.seconds
        totals["pt"] += res.prompt_tokens
        totals["ct"] += res.completion_tokens
        ckpt.append({"key": key, "text": res.text, "pt": res.prompt_tokens,
                     "ct": res.completion_tokens, "seconds": res.seconds,
                     "model": res.model, "ts": 0})
        return res.text

    trials = []
    for trial in range(1, args.trials + 1):
        loc = call(f"t{trial}:locate", LOCATE_SYS, locate_prompt(cands))
        try:
            roots = json.loads(loc).get("service_roots", [])
        except json.JSONDecodeError:
            roots = []
        roots = [r for r in roots if resolve(top, r) is not None]
        mapping = {}
        for rp in roots:
            root_stmt = resolve(top, rp)
            for node in base.enumerate_nodes(root_stmt, rp):
                lex = base.leaf_lexicon(node["leaves"])
                user = base.node_user_prompt(rp, node["path"], lex)
                final = call(f"t{trial}:{rp}:{node['path']}:map", base.REVIEW_SYS,
                             user + "\nPROPOSAL:{}")
                try:
                    chars = json.loads(final).get("characteristics", [])
                except json.JSONDecodeError:
                    chars = []
                for c in chars:
                    mapping[(rp, node["path"], c.get("yang_name"))] = (
                        c.get("tmf_name"), c.get("json_type"))
        trials.append({"trial": trial, "roots": sorted(roots), "mapping": mapping})
        cost = estimate_cost(provider.model, totals["pt"], totals["ct"])
        cost_s = f"~${cost:.3f}" if cost is not None else "n/a"
        print(f"[trial {trial}/{args.trials}] roots={sorted(roots)} "
              f"{totals['seconds']:6.1f}s {cost_s}")

    # ---- agreement scoring (no oracle) ----
    root_sets = collections.Counter(tuple(t["roots"]) for t in trials)
    modal_roots, modal_n = root_sets.most_common(1)[0]
    root_agreement = round(modal_n / len(trials), 3)
    agree_trials = [t for t in trials if tuple(t["roots"]) == modal_roots]

    # modal mapping over agree_trials
    keys = set()
    for t in agree_trials:
        keys |= set(t["mapping"].keys())
    per_key_mode = {}
    for k in keys:
        vals = collections.Counter(t["mapping"].get(k) for t in agree_trials)
        per_key_mode[k] = vals.most_common(1)[0][0]
    full_match = sum(1 for t in agree_trials
                     if all(t["mapping"].get(k) == per_key_mode[k] for k in keys))
    mapping_agreement = round(full_match / len(agree_trials), 3) if agree_trials else None

    cost = estimate_cost(provider.model, totals["pt"], totals["ct"])
    result = {
        "run_id": args.run_id, "model": provider.model, "trials": args.trials,
        "mode": "basic-unannotated",
        "candidate_nodes": len(cands),
        "metrics": {"api_calls_this_run": totals["calls"],
                    "seconds_this_run": round(totals["seconds"], 1),
                    "prompt_tokens": totals["pt"], "completion_tokens": totals["ct"],
                    "estimated_cost_usd": round(cost, 4) if cost is not None else None},
        "roots_per_trial": [{"trial": t["trial"], "roots": t["roots"]} for t in trials],
        "modal_service_roots": list(modal_roots),
        "root_agreement": root_agreement,
        "characteristics_in_modal": len(keys),
        "mapping_agreement_given_roots": mapping_agreement,
    }
    out_dir = os.path.join(ROOT, "out")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{args.run_id}-result.json")
    with open(path, "w") as fh:
        json.dump(result, fh, indent=2)

    print("\n" + "=" * 62)
    print("BASIC (unannotated) L3SM — ad hoc, no agreed mapping")
    print(f"agents chose roots {list(modal_roots)} in {modal_n}/{len(trials)} trials "
          f"(root agreement {root_agreement})")
    if mapping_agreement is not None:
        print(f"mapping agreement given those roots: {mapping_agreement} "
              f"over {len(keys)} characteristics")
    print("=" * 62)
    print(f"\nresult written: {path}")
    print("Drag that one file into the chat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
