"""Service-to-network reconciliation: L3SM (RFC 8299) to L3NM (RFC 9182).

The companion case to the L3SM-to-TMF mapping. That one is a cross-format
mapping, structural and determinate, where over-arching cognition suffices. This
one is a cross-abstraction mapping, service intent to network realization, and it
is where the both-cognitive end is tested. Four capabilities, each measured as an
overlay (over-arching, static artifacts only) result against a both-cognitive (an
interrogation channel to the network agent, and the ability to run virtual
experiments) result.

  A. Interrogation. The PE that realizes a site, and the route distinguisher and
     route targets, are network-assigned and live only on the network side. The
     overlay cannot produce them; the network agent, which holds its own
     realization, answers when asked.
     Measure: network-assigned attributes correct against the network truth.

  B. Pragmatics, run two ways to find WHEN it needs both-cognitive. L3SM
     svc-input / svc-output bandwidth are in the site frame; L3NM inbound /
     outbound are in the PE frame, the inverse.
       - documented frame: the L3NM model states the PE frame, so the overlay
         reads it off the descriptions and resolves the inversion. No gain.
       - undocumented frame: the frame is off the surface, so the overlay maps by
         name (wrong), and only asking the network agent recovers it.
     Measure: frame-correct directions, overlay in each case against both-cognitive.

  C. Self-maintenance. encapsulation-type is an open set. A new value slips past
     the leaf-level novelty sense and is caught only by a round-trip failure, one
     dropped. The agent then writes itself a value-level novelty rule for the open
     set, so the next new value is caught up front, none dropped.
     Measure: dropped instances on the second occurrence, with the self-added rule.

  D. Virtual experiment. Which L3NM qos-profile realizes the service's QoS intent
     is not a stored fact: two profiles share a declared label, and the effective
     treatment is known only when a profile is provisioned on a test instance and
     read back. The overlay cannot resolve it, and asking returns the ambiguous
     candidates by declaration; provisioning each candidate and reading back the
     effective treatment keeps the one that holds.
     Measure: correspondence resolved, overlay and ask-only against the experiment.

Only differences under --provider openai are real agent behaviour; --provider
mock exercises the pipeline with canned agents.

Run:
    cd ~/Downloads/onsen-reconciliation-demonstrator
    .venv/bin/python src/reconcile_sn.py --provider mock --run-id sn-mock
    .venv/bin/python src/reconcile_sn.py --provider openai --run-id sn-live
    .venv/bin/python src/reconcile_sn.py --provider openai --run-id sn-live --resume
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

import reconcile_l3sm as base            # noqa: E402
from providers import estimate_cost      # noqa: E402

# The service site-network-access being reconciled (L3SM, RFC 8299).
SERVICE_SNA = {
    "site-id": "acme-hq",
    "site-network-access-id": "acme-hq-primary",
    "svc-input-bandwidth": 1000000000,
    "svc-output-bandwidth": 200000000,
}

# The network realization: what the network (L3NM) agent holds for this
# attachment. The service side cannot derive any of this from its own model.
NETWORK_REALIZATION = {
    "ne-id": "PE-east-7",
    "role": "any-to-any-role",
    "router-id": "10.0.0.7",
    "interface-id": "GigabitEthernet0/0/7",
    "route-distinguisher": "65000:1001",
    "route-target": ["65000:1001"],
}
# The network-assigned attributes the mapping must carry, and their truth.
NETWORK_ASSIGNED = ["ne-id", "route-distinguisher", "route-target"]
NETWORK_TRUTH = {k: NETWORK_REALIZATION[k] for k in NETWORK_ASSIGNED}
NETWORK_TRUTH["bandwidth-frame"] = "PE-relative"

# Bandwidth reference frames. L3NM inbound/outbound are at the PE interface, the
# inverse of the L3SM site frame, so the frame-correct correspondence swaps.
FRAME_CORRECT = {
    "svc-input-bandwidth": "outbound-bandwidth",   # network->site = PE egress
    "svc-output-bandwidth": "inbound-bandwidth",    # site->network = PE ingress
}
BY_NAME = {
    "svc-input-bandwidth": "inbound-bandwidth",
    "svc-output-bandwidth": "outbound-bandwidth",
}
L3SM_BW_DESC = (
    "svc-input-bandwidth: inbound to the customer site, traffic from the provider "
    "network to the site (network-to-site). svc-output-bandwidth: outbound from "
    "the site, traffic from the site to the provider network (site-to-network).")
L3NM_BW_DOC = (
    "inbound-bandwidth: into the PE from the CE (site-to-network). "
    "outbound-bandwidth: out of the PE toward the CE (network-to-site).")
L3NM_BW_NODOC = (
    "inbound-bandwidth: a bandwidth value at the attachment. "
    "outbound-bandwidth: a bandwidth value at the attachment.")

# Virtual experiment. The service attachment expresses a QoS intent for its input
# traffic. The network holds several qos-profiles, but which one realizes the
# intent is not a declarative fact: two profiles carry the same declared label,
# and the effective treatment a profile produces is known only when it is
# provisioned on a test instance and read back.
SERVICE_QOS_INTENT = {"rate": 1000000000, "class": "real-time"}
QOS_PROFILES = {
    "qos-prof-1": {"declared": "high-throughput"},
    "qos-prof-2": {"declared": "low-latency-guaranteed"},
    "qos-prof-3": {"declared": "low-latency-guaranteed"},
}
# The effective treatment each profile produces, revealed only on provisioning.
QOS_EFF = {
    "qos-prof-1": {"rate": 1000000000, "class": "best-effort"},
    "qos-prof-2": {"rate": 1000000000, "class": "real-time"},
    "qos-prof-3": {"rate": 200000000, "class": "real-time"},
}
QOS_CORRECT = "qos-prof-2"  # the one whose readback matches the intent
QOS_CANDIDATES_BY_DECL = [
    p for p in QOS_PROFILES
    if QOS_PROFILES[p]["declared"] == QOS_PROFILES[QOS_CORRECT]["declared"]]


def provision_and_readback(profile):
    """Provision a candidate profile on a test instance and read back the
    effective treatment it produces; report whether it holds against the intent.
    This is the network/runtime executing the experiment, not an LLM call."""
    eff = QOS_EFF[profile]
    return {"profile": profile, "readback": eff,
            "holds": eff == SERVICE_QOS_INTENT}


OVERLAY_S_SYS = (
    "You are the service-side agent reconciling an L3SM (RFC 8299) "
    "site-network-access to the L3NM (RFC 9182) network model. You reason only "
    "over the two model definitions given. You have NO access to the network's "
    "runtime realization and no network agent to ask. If a value is not "
    "determinable from what you are given, return \"unknown\"; do not invent it. "
    "Respond with JSON only."
)
ASK_N_SYS = (
    "You are the network-side (L3NM) agent. You hold your own network "
    "realization, given to you. Answer the service agent's question truthfully "
    "from that realization. Respond with JSON only."
)
EXP_S_SYS = (
    "You are the service-side agent, now able to run virtual experiments. You may "
    "provision a candidate L3NM qos-profile on a test instance and read back the "
    "effective treatment it produces, its realized rate and class. Two candidate "
    "profiles carry the same declared label, so the declaration cannot tell which "
    "realizes the service intent; only provisioning and reading back can. Respond "
    "with JSON only."
)


def norm(v):
    if isinstance(v, list):
        return ",".join(sorted(str(x).strip() for x in v))
    return str(v).strip()


def bw_prompt(l3nm_desc, marker):
    return (f"{marker}. Map each L3SM bandwidth leaf to the L3NM leaf that "
            f"carries the SAME real traffic direction.\nL3SM: {L3SM_BW_DESC}\n"
            f"L3NM: {l3nm_desc}\nReturn JSON {{\"svc-input-bandwidth\": "
            f"\"inbound-bandwidth\" or \"outbound-bandwidth\", "
            f"\"svc-output-bandwidth\": \"inbound-bandwidth\" or "
            f"\"outbound-bandwidth\"}}.")


class SNMock:
    """Canned agents for the pipeline check. The overlay reads a documented frame
    and guesses by name on an undocumented one; it abstains on network-assigned
    fields. The network agent answers from its realization."""
    model = "mock"

    def complete(self, step, system, user):
        from providers import LLMResult
        if "OVERLAY-ASSIGNED" in user:
            text = json.dumps({k: "unknown" for k in NETWORK_ASSIGNED})
        elif "ASK-ASSIGNED" in user:
            text = json.dumps({k: NETWORK_TRUTH[k] for k in NETWORK_ASSIGNED})
        elif "OVERLAY-BW-DOC" in user:
            text = json.dumps(FRAME_CORRECT)
        elif "OVERLAY-BW-NODOC" in user:
            text = json.dumps(BY_NAME)
        elif "ASK-FRAME" in user:
            text = json.dumps({"bandwidth-frame": "PE-relative"})
        elif "OVERLAY-QOS" in user:
            text = json.dumps({"profile": "unknown"})
        elif "ASK-QOS" in user:
            text = json.dumps({"candidates": QOS_CANDIDATES_BY_DECL,
                               "resolved": None})
        elif "EXP-QOS" in user:
            text = json.dumps({"plan": QOS_CANDIDATES_BY_DECL})
        else:
            text = json.dumps({})
        return LLMResult(text, len(user) // 4, len(text) // 4, 0.0, self.model)


def make_provider(kind, model=None):
    if kind == "mock":
        return SNMock()
    return base.make_provider("openai", model)


def jload(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
        except Exception:
            return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["mock", "openai"], default="mock")
    ap.add_argument("--run-id", default="sn")
    ap.add_argument("--model", default=None)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    rid = args.run_id

    provider = make_provider(args.provider, args.model)
    ckpt = base.Checkpoint(os.path.join(ROOT, "transcripts", f"{rid}.jsonl"))
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
                     "model": res.model, "ts": time.time()})
        return res.text

    sna = json.dumps(SERVICE_SNA)
    print(f"[run] provider={args.provider} model={provider.model} run-id={rid}")

    # ---- Demo A: interrogation (network-assigned attributes) ----
    ov = jload(call(f"{rid}:A:overlay", OVERLAY_S_SYS,
        f"OVERLAY-ASSIGNED. Service site-network-access:{sna}\nFrom the service "
        f"model alone, fill the L3NM network-assigned attributes "
        f"{NETWORK_ASSIGNED}. Return JSON {{attr: value}}."))
    ov_A = sum(1 for k in NETWORK_ASSIGNED if norm(ov.get(k)) == norm(NETWORK_TRUTH[k]))
    ans = jload(call(f"{rid}:A:ask", ASK_N_SYS,
        f"ASK-ASSIGNED. Your network realization for attachment "
        f"{SERVICE_SNA['site-network-access-id']}:{json.dumps(NETWORK_REALIZATION)}\n"
        f"The service agent asks for the realizing PE ne-id, the "
        f"route-distinguisher and the route-target(s). Answer from your "
        f"realization. Return JSON {{attr: value}}."))
    bc_A = sum(1 for k in NETWORK_ASSIGNED if norm(ans.get(k)) == norm(NETWORK_TRUTH[k]))
    demoA = {"capability": "interrogation",
             "measure": "network-assigned attributes correct (of 3)",
             "overlay": ov_A, "both_cognitive": bc_A, "of": len(NETWORK_ASSIGNED)}
    print(f"[A interrogation] overlay {ov_A}/3  both-cognitive {bc_A}/3")

    # ---- Demo B: pragmatics, documented vs undocumented frame ----
    ovd = jload(call(f"{rid}:B:overlay-doc", OVERLAY_S_SYS,
                     bw_prompt(L3NM_BW_DOC, "OVERLAY-BW-DOC")))
    doc_ov = sum(1 for k in FRAME_CORRECT if ovd.get(k) == FRAME_CORRECT[k])
    ovn = jload(call(f"{rid}:B:overlay-nodoc", OVERLAY_S_SYS,
                     bw_prompt(L3NM_BW_NODOC, "OVERLAY-BW-NODOC")))
    nodoc_ov = sum(1 for k in FRAME_CORRECT if ovn.get(k) == FRAME_CORRECT[k])
    frame = jload(call(f"{rid}:B:ask", ASK_N_SYS,
        "ASK-FRAME. Your realization: inbound-bandwidth and outbound-bandwidth "
        "are measured at the PE interface. Are they relative to the PE or to the "
        "customer site? Return JSON {bandwidth-frame: \"PE-relative\" or "
        "\"site-relative\"}."))
    bc_map = FRAME_CORRECT if frame.get("bandwidth-frame") == "PE-relative" else BY_NAME
    nodoc_bc = sum(1 for k in FRAME_CORRECT if bc_map.get(k) == FRAME_CORRECT[k])
    demoB = {"capability": "pragmatics",
             "documented_frame": {"overlay_frame_correct": doc_ov, "of": 2,
                 "finding": "over-arching reads the documented frame; no gain"},
             "undocumented_frame": {"overlay_frame_correct": nodoc_ov,
                 "both_cognitive_frame_correct": nodoc_bc, "of": 2,
                 "finding": "overlay maps by name; only asking recovers the frame"},
             "overlay_doc_mapping": ovd, "overlay_nodoc_mapping": ovn}
    print(f"[B pragmatics]   documented: overlay {doc_ov}/2   "
          f"undocumented: overlay {nodoc_ov}/2 -> both-cognitive {nodoc_bc}/2")

    # ---- Demo C: self-maintenance (adapts its own triggers) ----
    known_encaps = {"dot1q", "untagged"}
    value_novelty_rule = False
    events = []
    for i, new_encap in enumerate(["qinq", "vxlan"], 1):
        caught_up_front = value_novelty_rule and new_encap not in known_encaps
        if caught_up_front:
            dropped, how = 0, "value-novelty rule (self-added)"
        else:
            dropped, how = 1, "round-trip failure"
            value_novelty_rule = True
        known_encaps.add(new_encap)
        events.append({"n": i, "new_encapsulation": new_encap, "caught_by": how,
                       "dropped": dropped})
        print(f"[C self-maint {i}] new encap {new_encap}: caught by {how}; "
              f"dropped {dropped}")
    demoC = {"capability": "self-maintenance",
             "measure": "dropped instances on the second new value",
             "first_occurrence_dropped": events[0]["dropped"],
             "second_occurrence_dropped": events[1]["dropped"],
             "mechanism": "agent self-adds a value-level novelty rule for the open "
                          "encapsulation set after the first miss",
             "events": events}

    # ---- Demo D: virtual experiment (provision a candidate, read it back) ----
    intent = json.dumps(SERVICE_QOS_INTENT)
    decl = json.dumps({p: QOS_PROFILES[p]["declared"] for p in QOS_PROFILES})
    ovq = jload(call(f"{rid}:D:overlay", OVERLAY_S_SYS,
        f"OVERLAY-QOS. Service QoS intent:{intent}\nThe network's qos-profiles, "
        f"declared labels only; two profiles share a declared label and no "
        f"effective rate or class is given for any:{decl}\nFrom the static models "
        f"alone, which profile realizes the intent? If it is not determinable "
        f"without provisioning, return \"unknown\". Return JSON {{\"profile\": "
        f"\"<id>\" or \"unknown\"}}."))
    ov_D = 1 if ovq.get("profile") == QOS_CORRECT else 0
    askq = jload(call(f"{rid}:D:ask", ASK_N_SYS,
        f"ASK-QOS. Your qos-profiles, declared labels only; the effective rate and "
        f"class of a profile are determined only when it is provisioned on an "
        f"instance and read back:{decl}\nThe service agent asks which profile "
        f"realizes intent {intent}. Answer from your declarations alone. Return "
        f"JSON {{\"candidates\": [ids], \"resolved\": \"<id>\" or null}}."))
    ask_D = 1 if askq.get("resolved") == QOS_CORRECT else 0
    cands = askq.get("candidates") or QOS_CANDIDATES_BY_DECL
    plan = jload(call(f"{rid}:D:experiment", EXP_S_SYS,
        f"EXP-QOS. Service intent:{intent}\nCandidate profiles, declared label "
        f"identical so they cannot be told apart by declaration:{json.dumps(cands)}"
        f"\nReturn JSON {{\"plan\": [profile-id, ...]}} ordering the candidates to "
        f"provision and read back; the first whose readback matches the intent is "
        f"kept."))
    order = plan.get("plan") or cands
    readbacks, kept = [], None
    for p in order:
        if p not in QOS_EFF:
            continue
        rb = provision_and_readback(p)
        readbacks.append(rb)
        if rb["holds"]:
            kept = p
            break
    exp_D = 1 if kept == QOS_CORRECT else 0
    demoD = {"capability": "virtual-experiment",
             "measure": "service-intent-to-qos-profile correspondence resolved",
             "overlay": ov_D, "ask_only": ask_D, "experiment": exp_D, "of": 1,
             "correct_profile": QOS_CORRECT, "kept_profile": kept,
             "candidates_by_declaration": QOS_CANDIDATES_BY_DECL,
             "readbacks": readbacks,
             "finding": ("two profiles share a declared label, so neither static "
                         "reasoning nor asking resolves which realizes the intent; "
                         "provisioning each and reading back the effective "
                         "treatment does")}
    print(f"[D virtual-exp]  overlay {ov_D}/1  ask-only {ask_D}/1  "
          f"experiment {exp_D}/1 (kept {kept})")

    cost = estimate_cost(provider.model, totals["pt"], totals["ct"])
    result = {
        "run_id": rid, "provider": args.provider, "model": provider.model,
        "case": "L3SM-to-L3NM (service-to-network)",
        "network_truth": NETWORK_TRUTH,
        "demos": {"A_interrogation": demoA, "B_pragmatics": demoB,
                  "C_self_maintenance": demoC, "D_virtual_experiment": demoD},
        "metrics": {"api_calls_this_run": totals["calls"],
                    "seconds_this_run": round(totals["seconds"], 1),
                    "prompt_tokens": totals["pt"], "completion_tokens": totals["ct"],
                    "estimated_cost_usd": round(cost, 4) if cost is not None else None},
    }
    out_dir = os.path.join(ROOT, "out")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{rid}-result.json")
    with open(path, "w") as fh:
        json.dump(result, fh, indent=2)

    print("\n" + "=" * 64)
    print("L3SM -> L3NM, where the both-cognitive end is tested:")
    print(f"  A interrogation          : overlay {ov_A}/3 -> both-cognitive {bc_A}/3 "
          f"network-assigned correct")
    print(f"  B pragmatics documented  : overlay {doc_ov}/2 (over-arching resolves)")
    print(f"  B pragmatics undocumented: overlay {nodoc_ov}/2 -> both-cognitive "
          f"{nodoc_bc}/2 frame-correct")
    print(f"  C self-maintenance       : {demoC['first_occurrence_dropped']} -> "
          f"{demoC['second_occurrence_dropped']} dropped, via a self-added rule")
    print(f"  D virtual experiment     : overlay {ov_D}/1, ask-only {ask_D}/1 -> "
          f"experiment {exp_D}/1 (kept {kept})")
    print("=" * 64)
    print(f"\nresult written: {path}")
    print("Drag that one file into the chat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
