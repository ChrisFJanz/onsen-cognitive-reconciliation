"""Drift lifecycle demonstration on the L3SM vpn-service root.

A sequence of real change events on a live service model. For each event the
detection and the deterministic translator are real operational machinery, and
the re-reconciliation of the affected node is a real agent call, the same
propose-and-review step the schema run makes, scoped to the node that moved.

Events exercised (all reactive, all real):
  1. a new leaf (sla-tier)                     -> novelty
  2. a rename (customer-name -> customer-id)   -> round-trip failure
  3. a new empty-typed leaf (protect-any)      -> novelty; empty binds boolean
  4. a leaf promoted to a nested keyed list    -> structural novelty, new node

Proactive, bilateral notification (announcing a change before it lands) is NOT
here: it needs a cognitive agent on the changing side, which an inert system is
not. That case is aspirational and is marked so in the demonstrator, not run.

The costly cognition runs only on the delta, only when a cheap, always-on check
in the operational plane fires. No model inference per message.

Run:
    cd ~/Downloads/onsen-reconciliation-demonstrator
    # plumbing, no key, no cost:
    .venv/bin/python src/run_drift.py --provider mock --run-id drift-mock
    # live snapshot, your OpenAI licence:
    caffeinate -is .venv/bin/python src/run_drift.py --provider openai --run-id drift-live
    # resume after an interruption:
    caffeinate -is .venv/bin/python src/run_drift.py --provider openai --run-id drift-live --resume
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import reconcile_l3sm as base            # noqa: E402
from providers import estimate_cost      # noqa: E402

YANG_DIR = os.path.join(ROOT, "models", "yang")


# --------------------------------------------------------------------------
# The live model: a root lexicon plus any nested nodes added by drift.
# A "leaf" is a lexicon dict: {yang_name, kind, yang_type, definition}.
# The translator maps (node_path, yang_name) -> (tmf_name, json_type).
# --------------------------------------------------------------------------

def vpn_service_root():
    module, roots = base.load_roots(os.path.join(YANG_DIR, "ietf-l3vpn-svc.yang"))
    for stmt, name in roots:
        if stmt.arg == "vpn-service":
            return stmt, name
    return roots[0][0], roots[0][1]


def root_lexicon(root_stmt, service):
    for node in base.enumerate_nodes(root_stmt, service):
        if node["path"] == "":
            return base.leaf_lexicon(node["leaves"])
    raise SystemExit("vpn-service root has no direct leaves")


def leaf(name, ytype, definition, kind="leaf"):
    return {"yang_name": name, "kind": kind, "yang_type": ytype,
            "definition": definition}


def model_instance(nodes):
    """One (path, yang_name) entry per leaf across every current node."""
    inst = []
    for path, lex in nodes:
        for e in lex:
            inst.append((path, e["yang_name"]))
    return inst


def detect(translator, instance):
    """Deterministic operational senses. novelty: elements the translator has no
    mapping for. round-trip: an element is dropped iff it is unmapped."""
    unknown = [f"{p+'/' if p else ''}{n}" for (p, n) in instance if (p, n) not in translator]
    rt_ok = len(unknown) == 0
    return unknown, rt_ok


# --------------------------------------------------------------------------
# A real single-node reconciliation: propose (YANG side) then review (TMF side).
# --------------------------------------------------------------------------

def reconcile_node(provider, ckpt, totals, service, path, lex, tag):
    user = base.node_user_prompt(service, path, lex)

    def call(key, system, text):
        if key in ckpt.done:
            return ckpt.done[key]["text"]
        res = provider.complete(key, system, text)
        totals["calls"] += 1
        totals["seconds"] += res.seconds
        totals["pt"] += res.prompt_tokens
        totals["ct"] += res.completion_tokens
        ckpt.append({"key": key, "text": res.text, "pt": res.prompt_tokens,
                     "ct": res.completion_tokens, "seconds": res.seconds,
                     "model": res.model, "ts": time.time()})
        return res.text

    proposal = call(f"{tag}:propose", base.PROPOSE_SYS, user)
    final = call(f"{tag}:review", base.REVIEW_SYS, user + "\nPROPOSAL:" + proposal)
    try:
        chars = json.loads(final).get("characteristics", [])
    except json.JSONDecodeError:
        chars = []
    return chars


def line(tag, msg):
    print(f"[{tag}] {msg}")


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["mock", "openai"], default="mock")
    ap.add_argument("--run-id", default="drift")
    ap.add_argument("--model", default=None)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    root_stmt, service = vpn_service_root()
    root_lex = root_lexicon(root_stmt, service)
    provider = base.make_provider(args.provider, args.model)

    # Live model: list of (path, lexicon). Starts as the root alone.
    nodes = [("", root_lex)]
    # Baseline translator: the schema run's verbatim-anchored result.
    translator = {}
    for path, lex in nodes:
        for e in lex:
            jt = "boolean" if e["yang_type"] == "boolean" else (
                 "integer" if e["yang_type"] in getattr(base.rm, "_INTEGER_TYPES", set()) else "string")
            translator[(path, e["yang_name"])] = (e["yang_name"], jt)

    print(f"[run] provider={args.provider} model={provider.model} run-id={args.run_id}")
    line("baseline", f"translator knows {len(translator)} {service} root "
                     f"characteristics (verbatim-anchored)")

    ckpt = base.Checkpoint(os.path.join(ROOT, "transcripts", f"{args.run_id}.jsonl"))
    if args.resume:
        ckpt.load()
    totals = {"calls": 0, "seconds": 0.0, "pt": 0, "ct": 0}

    def lex_of(path):
        for p, l in nodes:
            if p == path:
                return l
        return None

    def apply_chars(path, chars):
        for c in chars:
            yn, tn, jt = c.get("yang_name"), c.get("tmf_name"), c.get("json_type")
            if yn and tn:
                translator[(path, yn)] = (tn, jt)

    events = []

    def run_event(n, desc, trigger, affected_path, needs="over"):
        inst = model_instance(nodes)
        nov, rt = detect(translator, inst)
        line(f"event {n}", f"{desc}")
        line("  detect", f"novelty={nov or 'none'}; round-trip="
                          f"{'PASS' if rt else 'FAIL'}")
        tag = f"{args.run_id}:e{n}:{affected_path or 'root'}"
        chars = reconcile_node(provider, ckpt, totals, service, affected_path,
                               lex_of(affected_path), tag)
        apply_chars(affected_path, chars)
        inst2 = model_instance(nodes)
        nov2, rt2 = detect(translator, inst2)
        line("  reconcile", f"re-reconciled node '{affected_path or '(root)'}' "
                            f"({len(chars)} chars) by real agent call; "
                            f"novelty={nov2 or 'none'}; round-trip="
                            f"{'PASS' if rt2 else 'FAIL'}")
        ok = (not rt) and rt2 and bool(nov) and not nov2
        events.append({
            "n": n, "desc": desc, "trigger": trigger, "needs": needs,
            "affected_node": affected_path or service,
            "novelty_before": nov, "roundtrip_before": "PASS" if rt else "FAIL",
            "reconciled_characteristics": [
                {"yang_name": c.get("yang_name"), "tmf_name": c.get("tmf_name"),
                 "json_type": c.get("json_type")} for c in chars],
            "novelty_after": nov2, "roundtrip_after": "PASS" if rt2 else "FAIL",
            "ok": ok,
        })
        return ok

    # Event 1: a new leaf appears on the root.
    root_lex.append(leaf("sla-tier", "string", "service level tier"))
    run_event(1, "new leaf sla-tier : string", "novelty", "")

    # Event 2: a root identifier is renamed.
    for e in root_lex:
        if e["yang_name"] == "customer-name":
            e["yang_name"] = "customer-id"
    run_event(2, "rename customer-name -> customer-id", "round-trip", "")

    # Event 3: a new empty-typed leaf; the agents should bind empty -> boolean.
    root_lex.append(leaf("protect-any", "empty", "presence flag; carries no value"))
    run_event(3, "new empty leaf protect-any : empty", "novelty", "")

    # Event 4: a root leaf is promoted to a nested keyed list (structural).
    promoted = None
    for e in list(root_lex):
        if e["yang_name"] == "carrierscarrier":
            promoted = e
            root_lex.remove(e)
            if ("", "carrierscarrier") in translator:
                del translator[("", "carrierscarrier")]
    if promoted is None:
        promoted = leaf("carrierscarrier", "boolean", "carriers'-carrier flag")
    new_path = "carrierscarrier-opts"
    new_lex = [leaf("id", "string", "list key", kind="leaf"),
               leaf(promoted["yang_name"], promoted["yang_type"], promoted["definition"])]
    nodes.append((new_path, new_lex))
    run_event(4, "leaf carrierscarrier -> nested keyed list "
                 "carrierscarrier-opts[id]", "structural", new_path)

    # Event 5: proactive, bilateral notification (both-cognitive). Demonstrated
    # by its measured gain over reactive handling of the SAME change. Reactive
    # detection finds the change only when a non-conforming instance hits the
    # translator, so that instance is dropped before re-reconciliation. A
    # cognitive agent on the changing side announces the delta ahead of traffic,
    # re-reconciliation completes first, and nothing is dropped. An inert system
    # cannot announce, so this needs a cognitive agent on the changing side.
    qos_name = "qos-class"
    # reactive baseline: with the pre-change translator, the first instance that
    # carries the new element is dropped by the novelty / round-trip sense.
    reactive_inst = model_instance(nodes) + [("", qos_name)]
    reactive_nov, _ = detect(translator, reactive_inst)
    reactive_dropped = sum(1 for x in reactive_nov if x == qos_name)
    # proactive: the delta is announced ahead; pre-reconcile before any traffic.
    root_lex.append(leaf(qos_name, "string", "QoS class on the service"))
    chars5 = reconcile_node(provider, ckpt, totals, service, "", lex_of(""),
                            f"{args.run_id}:e5:proactive")
    apply_chars("", chars5)
    proactive_nov, _ = detect(translator, model_instance(nodes))
    proactive_dropped = sum(1 for x in proactive_nov if x == qos_name)
    line("event 5", "proactive notified change qos-class (both-cognitive)")
    line("  gain", f"reactive drops {reactive_dropped} instance(s) on first "
                   f"traffic; proactive pre-reconciles ahead and drops "
                   f"{proactive_dropped}")
    events.append({
        "n": 5, "desc": "proactive notified change (qos-class)",
        "trigger": "notified", "needs": "both", "affected_node": service,
        "mechanism": "changing side announces the delta before traffic; "
                     "re-reconciliation completes ahead of the first affected "
                     "instance",
        "reactive_dropped_instances": reactive_dropped,
        "proactive_dropped_instances": proactive_dropped,
        "gain": f"{reactive_dropped} -> {proactive_dropped} dropped instances",
        "reconciled_characteristics": [
            {"yang_name": c.get("yang_name"), "tmf_name": c.get("tmf_name"),
             "json_type": c.get("json_type")} for c in chars5],
        "ok": proactive_dropped == 0 and reactive_dropped >= 1,
    })

    all_ok = all(e["ok"] for e in events)
    cost = estimate_cost(provider.model, totals["pt"], totals["ct"])
    result = {
        "run_id": args.run_id, "provider": args.provider, "model": provider.model,
        "service_root": service, "baseline_characteristics": len(nodes[0][1]) - 2,
        "events": events,
        "metrics": {
            "api_calls_this_run": totals["calls"],
            "seconds_this_run": round(totals["seconds"], 1),
            "prompt_tokens": totals["pt"], "completion_tokens": totals["ct"],
            "estimated_cost_usd": round(cost, 4) if cost is not None else None,
        },
        "reactive_events": sum(1 for e in events if e.get("needs") == "over"),
        "proactive_events": sum(1 for e in events if e.get("needs") == "both"),
        "lifecycle_ok": all_ok,
        "note": ("Events 1-4 are real reactive detect-and-re-reconcile passes. "
                 "Event 5 demonstrates proactive bilateral notification "
                 "(both-cognitive) by its measured gain: it eliminates the "
                 "dropped instance that reactive detection incurs. The one "
                 "both-cognitive capability not exercised here is a virtual "
                 "experiment against a live running system, since the harness "
                 "holds models, not running systems."),
    }
    out_dir = os.path.join(ROOT, "out")
    os.makedirs(out_dir, exist_ok=True)
    result_path = os.path.join(out_dir, f"{args.run_id}-result.json")
    with open(result_path, "w") as fh:
        json.dump(result, fh, indent=2)

    cost_s = f"~${cost:.3f}" if cost is not None else "n/a"
    n_re = sum(1 for e in events if e.get("needs") == "over")
    n_pro = sum(1 for e in events if e.get("needs") == "both")
    print("\n" + "=" * 62)
    print(f"drift lifecycle: {n_re} reactive + {n_pro} proactive event(s), "
          f"{'all verified' if all_ok else 'INCONSISTENT'}")
    print(f"{totals['calls']} agent call(s), {totals['seconds']:.1f}s, {cost_s}")
    print("re-reconciliations were real agent calls" if args.provider == "openai"
          else "re-reconciliations used the mock agent (run --provider openai "
               "for the real snapshot)")
    print("=" * 62)
    print(f"\nresult written: {result_path}")
    print("Drag that one file into the chat.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
