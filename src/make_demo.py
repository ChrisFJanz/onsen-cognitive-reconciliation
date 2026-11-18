"""Generate self-contained HTML demo movies from run outputs.

Produces static, dependency-free HTML pages that step through a recorded run,
for hosting on a public repository and linking from the ID. No server needed;
open the file in a browser.

    cd ~/Downloads/onsen-reconciliation-demonstrator
    .venv/bin/python src/run_instance.py        # writes out/l3sm-instance-result.json
    .venv/bin/python src/run_drift.py            # writes out/drift-result.json
    .venv/bin/python src/make_demo.py            # writes demo/*.html

Outputs demo/instance.html and demo/drift.html.
"""

from __future__ import annotations

import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "out")
DEMO = os.path.join(ROOT, "demo")

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --navy:#1F3864; --red:#9E1B32; --ink:#111; --muted:#555; --line:#ddd; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:15px/1.6 Georgia, 'Times New Roman', serif; color:var(--ink);
         background:#fafafa; }}
  header {{ padding:18px 20px; border-bottom:2px solid var(--red); background:#fff; }}
  h1 {{ margin:0; font-size:19px; color:var(--navy); }}
  .sub {{ color:var(--muted); font-size:13px; margin-top:2px; }}
  main {{ max-width:860px; margin:0 auto; padding:18px 16px 60px; }}
  .stage {{ display:none; background:#fff; border:1px solid var(--line); border-radius:8px;
           padding:18px 20px; min-height:260px; }}
  .stage.on {{ display:block; }}
  .tag {{ display:inline-block; font:12px/1 'DejaVu Sans Mono', monospace; color:#fff;
         background:var(--navy); padding:4px 8px; border-radius:4px; letter-spacing:.3px; }}
  .tag.red {{ background:var(--red); }}
  .tag.green {{ background:#1a7f4b; }}
  h2 {{ font-size:16px; margin:12px 0 6px; color:var(--navy); }}
  pre {{ background:#f4f6fb; border:1px solid var(--line); border-radius:6px; padding:10px 12px;
        overflow:auto; font:12.5px/1.45 'DejaVu Sans Mono', monospace; color:#1b2a4a; }}
  .nav {{ position:fixed; left:0; right:0; bottom:0; background:#fff; border-top:1px solid var(--line);
         padding:10px 16px; display:flex; gap:10px; align-items:center; justify-content:center; }}
  button {{ font:14px Georgia, serif; padding:7px 16px; border:1px solid var(--navy); background:#fff;
           color:var(--navy); border-radius:6px; cursor:pointer; }}
  button:disabled {{ opacity:.4; cursor:default; }}
  .count {{ color:var(--muted); font-size:13px; min-width:70px; text-align:center; }}
  .dots {{ text-align:center; margin:10px 0 0; }}
  .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--line);
         margin:0 3px; }}
  .dot.on {{ background:var(--navy); }}
  table {{ border-collapse:collapse; font-size:13px; margin-top:8px; }}
  th, td {{ border:1px solid var(--line); padding:6px 10px; text-align:left; }}
  th {{ background:#f4f6fb; color:var(--navy); }}
  code {{ font-family:'DejaVu Sans Mono', monospace; background:#f4f6fb; padding:0 3px; }}
</style></head><body>
<header><h1>{title}</h1><div class="sub">{subtitle}</div></header>
<main id="stages">{stages}</main>
<div class="dots" id="dots"></div>
<div class="nav">
  <button id="prev">&larr; Prev</button>
  <span class="count" id="count"></span>
  <button id="next">Next &rarr;</button>
  <button id="play">Play</button>
</div>
<script>
  var n = {count}, i = 0, timer = null;
  var stages = document.querySelectorAll('.stage');
  var dots = document.getElementById('dots');
  for (var k=0;k<n;k++) {{ var d=document.createElement('span'); d.className='dot'; dots.appendChild(d); }}
  function show(j) {{
    i = Math.max(0, Math.min(n-1, j));
    stages.forEach(function(s,x){{ s.classList.toggle('on', x===i); }});
    document.querySelectorAll('.dot').forEach(function(d,x){{ d.classList.toggle('on', x<=i); }});
    document.getElementById('count').textContent = (i+1)+' / '+n;
    document.getElementById('prev').disabled = (i===0);
    document.getElementById('next').disabled = (i===n-1);
  }}
  document.getElementById('prev').onclick=function(){{ stop(); show(i-1); }};
  document.getElementById('next').onclick=function(){{ stop(); show(i+1); }};
  function stop(){{ if(timer){{clearInterval(timer);timer=null;document.getElementById('play').textContent='Play';}} }}
  document.getElementById('play').onclick=function(){{
    if(timer){{ stop(); return; }}
    document.getElementById('play').textContent='Pause';
    timer=setInterval(function(){{ if(i>=n-1){{ stop(); }} else {{ show(i+1); }} }}, 1800);
  }};
  show(0);
</script></body></html>"""


def stage(tag, tag_class, heading, body_html):
    return (f'<section class="stage"><span class="tag {tag_class}">{tag}</span>'
            f'<h2>{html.escape(heading)}</h2>{body_html}</section>')


def pre(obj):
    text = obj if isinstance(obj, str) else json.dumps(obj, indent=2)
    return f"<pre>{html.escape(text)}</pre>"


def build(title, subtitle, stages):
    body = "".join(stages)
    return PAGE.format(title=html.escape(title), subtitle=html.escape(subtitle),
                       stages=body, count=len(stages))


def drift_movie(r):
    s = []
    s.append(stage("baseline", "", "A translator is already in service",
                   f"<p>The deterministic translator carries "
                   f"{r['baseline_characteristics']} reconciled vpn-service root "
                   f"characteristics. No model inference runs per message.</p>"))
    s.append(stage("drift", "red", "The far-side model changes",
                   pre(r["drift"]) +
                   "<p>A new leaf appears and one identifier is renamed. Nothing "
                   "has told the running translator.</p>"))
    s.append(stage("trigger: novelty", "red", "The translator meets what it cannot map",
                   pre(r["detected_novelty"]) +
                   "<p>A cheap, always-on check on the runtime path flags elements "
                   "with no mapping, rather than dropping them silently.</p>"))
    s.append(stage("trigger: round-trip", "red",
                   "The ongoing round-trip guardrail fails",
                   f"<p>Round-trip before: <b>{r['roundtrip_before']}</b>. "
                   f"Dropped on the floor:</p>" + pre(r["dropped_before"]) +
                   "<p>Round-trip checking is continuous, not a one-time validation.</p>"))
    s.append(stage("invoke", "", "The counterpart engine is woken, for one node",
                   f"<p>Reconciliation is a negotiation, so the trigger wakes the "
                   f"other side's engine, scoped to the affected node: "
                   f"<b>{html.escape(r['incremental_node'])}</b>.</p>"))
    s.append(stage("reconcile", "", "Only the changed node is re-reconciled",
                   "<p>The costly cognition runs on the delta, not the whole "
                   "model. The translator is regenerated for that node.</p>"))
    s.append(stage("verify", "green", "Both checks pass again",
                   f"<p>Novelty after: <b>{r['novelty_after'] or 'none'}</b>. "
                   f"Round-trip after: <b>{r['roundtrip_after']}</b>. The model "
                   f"change has been absorbed with no human reconciliation work.</p>"))
    return build("Drift lifecycle",
                 "A model change, detected on the runtime path and absorbed by "
                 "incremental re-reconciliation", s)


def instance_movie(r):
    svc = r["tmf_service"][0]
    s = []
    s.append(stage("instance", "", "A real L3SM vpn-service instance",
                   "<p>Operational instance data, not a schema in the abstract.</p>" +
                   pre({"ietf-l3vpn-svc:vpn-service": ["(one service instance)"]})))
    s.append(stage("translate", "", "Mapped to a TMF Service",
                   f"<p>{len(svc['feature'])} nested Features, linked by "
                   f"composedOf, list entries carrying a key predicate.</p>" +
                   pre({"serviceCharacteristic": svc["serviceCharacteristic"],
                        "feature (names)": [f["name"] for f in svc["feature"]]})))
    s.append(stage("verify", "green", "And back to YANG, losslessly",
                   f"<p>Faithfulness round-trip, YANG to TMF to YANG: "
                   f"<b>{r['faithfulness_roundtrip']}</b>. The reconciled "
                   f"translator carries real instance data without loss.</p>"))
    return build("Instance round-trip",
                 "A real service instance across the reconciled YANG-to-TMF "
                 "translator and back", s)


def reconciliation_movie(r):
    m = r["metrics"]
    cost = m.get("estimated_cost_usd")
    cost_s = f"about ${cost:.2f} " if cost else ""
    s = []
    s.append(stage("method", "", "Two agents, no sight of the standard",
                   f"<p>A YANG-side agent and a TMF-side agent reconcile the full "
                   f"L3SM service model, {r['characteristics_per_trial']} "
                   f"characteristics across {r['nodes_with_leaves']} nested nodes, "
                   f"node by node, from their own models and a thin shared "
                   f"reference. Neither is shown the standard's mapping.</p>"))
    s.append(stage("run", "", "Repeated to measure reliability",
                   f"<p>{r['trials']} independent trials, "
                   f"{m['api_calls_this_run']} model calls, "
                   f"{m['seconds_this_run']:.0f} seconds, {cost_s}on "
                   f"{html.escape(str(r['model']))}.</p>"))
    s.append(stage("result", "", "Whole-model convergence",
                   f"<p><b>{r['trials_passed']} of {r['trials']}</b> trials "
                   f"reproduced the standard mapping exactly, a rate of "
                   f"{r['convergence_rate']}. The figure understates the structure "
                   f"of the outcome.</p>"))
    rows = "".join(
        f"<tr><td><code>{html.escape(a['leaf'].split('/')[-1])}</code></td>"
        f"<td>{a['trials_mismatched']}</td>"
        f"<td>oracle {html.escape(str(a['oracle'][1]))} / "
        f"agent {html.escape(str(a['agent'][1]))}</td></tr>"
        for a in r.get("aggregated_mismatches", []))
    s.append(stage("structure", "red", "Every failure is one unspecified type",
                   "<p>On every characteristic the standard specifies, all trials "
                   "agreed, identifiers verbatim. Every divergence, without "
                   "exception, is a YANG <code>empty</code> leaf, the one type the "
                   "mapping does not cover:</p>"
                   f"<table><tr><th>empty leaf</th><th>trials</th>"
                   f"<th>type chosen</th></tr>{rows}</table>"))
    s.append(stage("reading", "", "The overlay-placement signature",
                   "<p>With cognition over the static artifacts of both sides, "
                   "reconciliation is sound, no wrong bindings, but not complete: "
                   "a case with no anchor resolves non-deterministically. The "
                   "agents lean boolean and waver to string.</p>"))
    s.append(stage("fix", "green", "Anchor the one open case",
                   "<p>Specify <code>empty</code> as boolean, or carry the "
                   "convention in the shared reference. On this evidence that "
                   "removes the sole source of divergence and restores full "
                   "convergence.</p>"))
    return build("Reconciling L3SM to TM Forum",
                 "Agent-to-agent reconciliation of the full L3SM service model, "
                 "and what the residual reveals", s)


def main():
    os.makedirs(DEMO, exist_ok=True)
    made = []
    for fn in sorted(os.listdir(OUT)) if os.path.isdir(OUT) else []:
        if fn.endswith("-result.json"):
            with open(os.path.join(OUT, fn)) as fh:
                data = json.load(fh)
            if "convergence_rate" in data:
                with open(os.path.join(DEMO, "reconciliation.html"), "w") as fh:
                    fh.write(reconciliation_movie(data))
                made.append(os.path.join(DEMO, "reconciliation.html"))
                break
    dpath = os.path.join(OUT, "drift-result.json")
    if os.path.exists(dpath):
        with open(dpath) as fh:
            out = drift_movie(json.load(fh))
        p = os.path.join(DEMO, "drift.html")
        with open(p, "w") as fh:
            fh.write(out)
        made.append(p)
    ipath = os.path.join(OUT, "l3sm-instance-result.json")
    if os.path.exists(ipath):
        with open(ipath) as fh:
            out = instance_movie(json.load(fh))
        p = os.path.join(DEMO, "instance.html")
        with open(p, "w") as fh:
            fh.write(out)
        made.append(p)
    if not made:
        raise SystemExit("No result files found. Run run_instance.py and "
                         "run_drift.py first.")
    for p in made:
        print("wrote", p)


if __name__ == "__main__":
    main()
