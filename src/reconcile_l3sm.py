"""Stage 2: agent-to-agent reconciliation over a real, nested service model.

Anchors on the L3SM (RFC 8299) vpn-service subtree, annotated with a single
tmf:cfs-service line. The subtree is reconciled node by node: for each container
or list, a YANG-side agent and a TMF-side agent agree how that node's direct
leaves map to TMF characteristics (name and JSON type), under the same shared-
reference naming anchor proven on the toaster. The feature tree itself (the
composedOf structure) is fixed by the YANG tree, so what the agents actually
decide, and what we score, is the naming and typing of every characteristic.

The whole subtree is reconciled once per trial, and the run repeats for several
trials, so the result is a convergence rate: how often the agents reproduce the
standard's mapping exactly, and where they diverge when they do not. Every node
of every trial is checkpointed to transcripts/<run>.jsonl, so an interrupted run
resumes with --resume and makes no repeated API calls.

Scoring is against the deterministic reference mapper (the oracle), at the level
the agents negotiate: characteristic name and JSON type for every leaf. Constraint
specs and instance round-tripping on L3SM are the next increment.

Run:
    cd ~/Downloads/onsen-reconciliation-demonstrator
    # plumbing, no key, no cost:
    .venv/bin/python src/reconcile_l3sm.py --provider mock --run-id l3sm-mock --trials 2
    # live, your OpenAI licence:
    .venv/bin/python src/reconcile_l3sm.py --provider openai --run-id l3sm-live --trials 5
    # resume after an interruption:
    .venv/bin/python src/reconcile_l3sm.py --provider openai --run-id l3sm-live --trials 5 --resume
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import reference_mapper as rm            # noqa: E402
from providers import estimate_cost      # noqa: E402

YANG_DIR = os.path.join(ROOT, "models", "yang")

TMF_CONVENTIONS = (
    "Map each YANG leaf or leaf-list to one TMF characteristic. json_type is the "
    "JSON Schema type of the YANG base type: boolean->boolean, "
    "string/enumeration/identityref/leafref->string, integer types->integer, "
    "decimal64->number; a leaf-list uses the matching array type "
    "(booleanArray/stringArray/integerArray/numberArray). Shared-reference naming "
    "anchor: tmf_name is the YANG node identifier verbatim, no renaming or case "
    "change ('customer-name' stays 'customer-name', never 'customerName')."
)

PROPOSE_SYS = (
    "You are the YANG-side cognitive agent reconciling one node of a service "
    "model with a TMF consumer. Given this node's leaves, return JSON "
    "{\"characteristics\": [{\"yang_name\", \"tmf_name\", \"json_type\"}]}. "
    "Respond with JSON only."
)
REVIEW_SYS = (
    "You are the TMF-side cognitive agent. Check the proposal against the leaves "
    "and the conventions, fix any wrong json_type or any tmf_name that is not the "
    "YANG identifier verbatim, and return the final "
    "{\"characteristics\": [...]}. Respond with JSON only."
)


# --------------------------------------------------------------------------
# Node enumeration and the oracle
# --------------------------------------------------------------------------

def load_roots(schema_path: str):
    ctx = rm.load_context(YANG_DIR)
    rm.add_module(ctx, os.path.join(YANG_DIR, "ietf-yang-tmf-map.yang"))
    module = rm.add_module(ctx, schema_path)
    ctx.validate()
    roots = rm._find_annotated_roots(module)
    if not roots:
        raise SystemExit(f"no tmf-annotated root found in {schema_path}")
    return module, [(stmt, ann[1]) for stmt, ann in roots]


def enumerate_nodes(root_stmt, service) -> list[dict]:
    """Ordered nodes (root plus every nested container/list) that have at least
    one direct leaf to map, tagged with their service root."""
    nodes: list[dict] = []

    def visit(stmt, is_root):
        leaves = [c for c in rm._data_children(stmt)
                  if c.keyword in ("leaf", "leaf-list")]
        if leaves:
            path = "" if is_root else rm._feature_name(stmt, root_stmt)
            nodes.append({"stmt": stmt, "service": service,
                          "path": path, "leaves": leaves})
        for c in rm._data_children(stmt):
            if c.keyword in ("container", "list"):
                visit(c, False)

    visit(root_stmt, True)
    return nodes


def oracle_value_type(leaf) -> str:
    t = leaf.search_one("type")
    jt = rm.jsonschema_type(t)
    return rm._array_type(jt) if leaf.keyword == "leaf-list" else jt


def leaf_lexicon(leaves) -> list[dict]:
    out = []
    for leaf in leaves:
        t = leaf.search_one("type")
        d = leaf.search_one("description")
        out.append({
            "yang_name": leaf.arg,
            "kind": leaf.keyword,
            "yang_type": rm._base_type_name(t),
            "definition": (d.arg.strip() if d is not None and d.arg else ""),
        })
    return out


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

class Stage2Mock:
    """Perfect-agent mock: reads the node's leaves from the prompt and returns
    the verbatim-name, correctly typed mapping. Exercises the full parse,
    assembly, scoring, checkpoint and resume path with no key and no cost."""

    model = "mock"

    def complete(self, step, system, user):
        marker = "LEAVES:"
        start = user.index(marker) + len(marker)
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
        return _Result(text, len(user) // 4, len(text) // 4, 0.0, self.model)


class _Result:
    def __init__(self, text, pt, ct, secs, model):
        self.text = text
        self.prompt_tokens = pt
        self.completion_tokens = ct
        self.seconds = secs
        self.model = model


def make_provider(kind, model=None):
    if kind == "mock":
        return Stage2Mock()
    if kind == "openai":
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(ROOT, ".env"))
        except Exception:
            pass
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit("OPENAI_API_KEY not set; write it into .env first.")
        from providers import OpenAIProvider
        return OpenAIProvider(model)
    raise SystemExit(f"unknown provider: {kind}")


# --------------------------------------------------------------------------
# Checkpointed runner
# --------------------------------------------------------------------------

class Checkpoint:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.done = {}

    def load(self):
        if not os.path.exists(self.path):
            return
        with open(self.path) as fh:
            for line in fh:
                rec = json.loads(line)
                self.done[rec["key"]] = rec
        if self.done:
            print(f"[resume] replayed {len(self.done)} checkpointed call(s), "
                  f"0 API calls")

    def append(self, rec):
        with open(self.path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self.done[rec["key"]] = rec


def node_user_prompt(service, path, leaves_lex) -> str:
    where = f"{service}:{path or '(service root)'}"
    return (f"Node: {where}\n{TMF_CONVENTIONS}\nLEAVES:{json.dumps(leaves_lex)}")


def run(provider, nodes, trials, ckpt, resume):
    if resume:
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
        ckpt.append({"key": key, "text": res.text,
                     "pt": res.prompt_tokens, "ct": res.completion_tokens,
                     "seconds": res.seconds, "model": res.model, "ts": time.time()})
        return res.text

    agent_by_trial = []
    for trial in range(1, trials + 1):
        agent = {}
        for node in nodes:
            lex = leaf_lexicon(node["leaves"])
            user = node_user_prompt(node["service"], node["path"], lex)
            base = f"{node['service']}|t{trial}:{node['path']}"
            proposal = call(base + ":propose", PROPOSE_SYS, user)
            final = call(base + ":review", REVIEW_SYS,
                         user + "\nPROPOSAL:" + proposal)
            try:
                chars = json.loads(final).get("characteristics", [])
            except json.JSONDecodeError:
                chars = []
            for c in chars:
                agent[(node["service"], node["path"], c.get("yang_name"))] = (
                    c.get("tmf_name"), c.get("json_type"))
        agent_by_trial.append(agent)
        cost = estimate_cost(provider.model, totals["pt"], totals["ct"])
        cost_s = f"~${cost:.3f}" if cost is not None else "n/a"
        print(f"[trial {trial}/{trials}] {totals['seconds']:6.1f}s cumulative, "
              f"{totals['calls']} calls, {cost_s}")
    return agent_by_trial, totals


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def build_oracle(nodes) -> dict:
    oracle = {}
    for node in nodes:
        for leaf in node["leaves"]:
            oracle[(node["service"], node["path"], leaf.arg)] = (
                leaf.arg, oracle_value_type(leaf))
    return oracle


def score(agent_by_trial, oracle):
    per_trial = []
    mismatch_counts = {}
    examples = {}
    for i, agent in enumerate(agent_by_trial, 1):
        mism = []
        for key, exp in oracle.items():
            got = agent.get(key)
            if got != exp:
                mism.append(key)
                mismatch_counts[key] = mismatch_counts.get(key, 0) + 1
                examples.setdefault(key, {"oracle": exp, "agent": got})
        per_trial.append({"trial": i, "pass": len(mism) == 0,
                          "mismatches": len(mism)})
    passes = sum(1 for t in per_trial if t["pass"])
    aggregated = [
        {"leaf": f"{s}:{p}/{n}" if p else f"{s}:{n}",
         "trials_mismatched": c,
         "oracle": list(examples[(s, p, n)]["oracle"]),
         "agent": list(examples[(s, p, n)]["agent"]) if examples[(s, p, n)]["agent"] else None}
        for (s, p, n), c in sorted(mismatch_counts.items(), key=lambda kv: -kv[1])
    ]
    return per_trial, passes, aggregated


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["mock", "openai"], default="mock")
    ap.add_argument("--run-id", default="l3sm")
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--model", default=None,
                    help="exact OpenAI model id; overrides OPENAI_MODEL in .env")
    ap.add_argument("--schema", default=os.path.join(YANG_DIR, "ietf-l3vpn-svc.yang"))
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    module, roots = load_roots(args.schema)
    nodes = []
    for root_stmt, name in roots:
        nodes += enumerate_nodes(root_stmt, name)
    oracle = build_oracle(nodes)
    provider = make_provider(args.provider, args.model)

    n_chars = len(oracle)
    root_names = ", ".join(name for _, name in roots)
    print(f"[run] provider={args.provider} model={provider.model} "
          f"run-id={args.run_id} trials={args.trials}")
    print(f"[model] L3SM roots [{root_names}]: {len(nodes)} nodes with leaves, "
          f"{n_chars} characteristics per trial")

    ckpt = Checkpoint(os.path.join(ROOT, "transcripts", f"{args.run_id}.jsonl"))
    agent_by_trial, totals = run(provider, nodes, args.trials, ckpt, args.resume)
    per_trial, passes, aggregated = score(agent_by_trial, oracle)

    cost = estimate_cost(provider.model, totals["pt"], totals["ct"])
    result = {
        "run_id": args.run_id,
        "provider": args.provider,
        "model": provider.model,
        "trials": args.trials,
        "characteristics_per_trial": n_chars,
        "nodes_with_leaves": len(nodes),
        "metrics": {
            "api_calls_this_run": totals["calls"],
            "seconds_this_run": round(totals["seconds"], 1),
            "prompt_tokens": totals["pt"],
            "completion_tokens": totals["ct"],
            "estimated_cost_usd": round(cost, 4) if cost is not None else None,
        },
        "trials_passed": passes,
        "convergence_rate": round(passes / args.trials, 3) if args.trials else None,
        "per_trial": per_trial,
        "aggregated_mismatches": aggregated,
    }
    out_dir = os.path.join(ROOT, "out")
    os.makedirs(out_dir, exist_ok=True)
    result_path = os.path.join(out_dir, f"{args.run_id}-result.json")
    with open(result_path, "w") as fh:
        json.dump(result, fh, indent=2)

    print("\n" + "=" * 62)
    print(f"L3SM [{root_names}], {args.trials} trial(s), "
          f"{n_chars} characteristics each")
    print(f"converged on the standard mapping: {passes}/{args.trials} trials")
    if aggregated:
        print("where they diverged (most frequent first):")
        for a in aggregated[:10]:
            print(f"  {a['leaf']}: {a['trials_mismatched']}x  "
                  f"oracle={a['oracle']} agent={a['agent']}")
    print("=" * 62)
    print(f"\nresult written: {result_path}")
    print("Drag that one file into the chat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
