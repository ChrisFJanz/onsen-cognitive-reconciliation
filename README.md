# ONSEN reconciliation demonstrator

Showing that agent-to-agent ontology reconciliation builds and maintains the
YANG-to-TMF adapter that draft-lls-onsen-yang-tmf-mapping sets out to
standardize, and that for cognitive systems building it is no burden.

## What's new

### 2026-11-17 · service-to-network case, drift upgrade, demonstrator movie
- Authority-withheld (standard-free) locate added to the L3SM harness: given the
  plain RFC 8299 model with no mapping-root annotations, the agents must locate
  the customer-facing services themselves. Over ten trials they agreed on the
  service roots three times; the split sorts into granularity, a false cognate
  (a profile library), and an authority boundary (is a site a service) that no
  reasoning closes. This sizes the authority boundary against the authority-given
  run.
- Drift lifecycle upgraded (`src/run_drift.py`): five real change events on the
  vpn-service root. Four reactive (a new leaf, a rename, a new empty-typed leaf,
  a leaf promoted to a nested keyed list), each caught by the novelty or
  round-trip sense and re-reconciled on the affected node by a real agent call;
  and one proactive notification, measured against reactive handling, 0 dropped
  instances versus 1.
- Service-to-network case added (`src/reconcile_sn.py`; L3SM RFC 8299 to L3NM
  RFC 9182, `models/yang/ietf-l3vpn-ntw-extract.yang`): the cross-abstraction
  pole, exercising four capabilities against the over-arching placement.
  Interrogation (network-assigned ne-id, RD, route targets; overlay 0/3, asking
  3/3). Pragmatics (bandwidth site frame vs PE frame; documented 2/2, undocumented
  0/2 to 2/2 by asking). Self-maintenance (open encapsulation set; 1 dropped to 0
  via a self-added value-novelty rule). Virtual experiment (which L3NM qos-profile
  realizes the service intent; overlay 0/1, asking 0/1, experiment 1/1 by
  provision-and-readback).
- Design fault found and fixed in the service-to-network harness: the first
  sn-live run scored interrogation 0/3 because the network agent was never given
  its own realization to answer from. Fixed by passing the realization to the
  network agent; the affected results were rerun on the corrected code and are the
  ones reported.
- Step-through demonstrator movie (`demo-movies/reconciliation-live.html`): a
  single self-contained page walking the whole process, marked for where each
  stage sits on the cognition-placement spectrum and whether more cognition would
  add anything. The two reconciliation blocks relabel per placement: roles of one
  over-arching reasoner over inert artifacts, or live agents on each side.

### 2026-11-17 · foundations
- Repo scaffolded.
- Local copy of the `ietf-yang-tmf-map` annotation module (`cfs-service`,
  `rfs-service`, `resource`, `ignore`), per draft-lls-onsen-yang-tmf-mapping-00.
- Representative annotated `example-toaster` model exercising every mapping
  rule in the draft's sections 3 and 4.
- Deterministic **reference mapper** (`src/reference_mapper.py`) implementing
  the draft's normative YANG-to-TMF rules. This is the demonstrator's oracle:
  "what the standard would produce."
- Stage 0 proof (`src/run_toaster.py`): the reference mapper emits the toaster's
  TMF `ServiceSpecification`, maps a YANG instance to a TMF `Service` and back,
  and the faithfulness round-trip returns the original. No API calls, no cost.
- Stage 1 **reconciliation harness** (`src/reconcile.py`, `src/run_reconcile.py`):
  a YANG-side agent and a TMF-side agent negotiate a mapping table from the YANG
  reference lexicon (`src/lexicon.py`) and the TMF conventions, never shown the
  draft's spec. A deterministic executor (`src/translator.py`) applies the table.
  Provider abstraction (`src/providers.py`): OpenAI for live runs, a mock for
  offline plumbing checks. Every step is checkpointed to `transcripts/<run>.jsonl`;
  `--resume` replays saved steps with zero API calls and continues, so an
  interrupted run loses at most the one call in flight. Per-call and cumulative
  wall-clock, token count and estimated cost are printed as the run proceeds.
  Validated end-to-end with the mock, including mid-run resume.
- First live run (gpt-4o) design pitfall found and fixed: absent a shared
  naming convention, the TMF-side agent renamed hyphenated YANG identifiers to
  camelCase (`serial-number` to `serialNumber`), so faithfulness passed but
  equivalence failed. The names are now pinned as a shared-reference naming
  anchor (characteristic name is the YANG identifier, verbatim, taken from the
  lexicon term), which is the draft-janz-nmrg-reference-lexicons mechanism.
- Each run now writes a self-contained `out/<run-id>-result.json` with scores,
  the agent-vs-oracle name diff, timing and the negotiated table.
- Stage 2 (L3SM, RFC 8299): annotated working copy of `ietf-l3vpn-svc` carrying
  `tmf:cfs-service` on both the `vpn-service` and the `site` lists. The reference
  mapper now descends `choice`/`case` nodes and keeps those wrapper names out of
  feature paths. The two roots together cover 90 nested nodes and 209
  characteristics. New multi-root, multi-trial driver (`src/reconcile_l3sm.py`)
  reconciles each subtree node by node, repeats over N independent trials,
  checkpoints every node of every trial, and reports a convergence rate against
  the oracle. Validated with the mock including resume. Scope: scored at
  characteristic name and JSON type; constraint specs and L3SM instance
  round-trip are next.
- First live L3SM run (gpt-4o, 20 trials, vpn-service, $0.67): the agents
  reproduced every specified mapping 20/20 with names verbatim. The only
  recurring difference was `permit-any`, a YANG `empty` leaf the draft's section
  4 type table does not cover; all 20 trials chose `boolean`, the oracle had
  defaulted to `string`. `empty` is a genuine gap in the draft. Oracle corrected
  to `empty`->`boolean`, the agents' unanimous and better choice; with it the
  vpn-service run reads 20/20 clean. A finding for the draft authors.
- Operational-concrete instance mapping (`src/instance_mapper.py`,
  `src/run_instance.py`): a real L3SM `vpn-service` instance maps to a TMF
  Service with nested features and `composedOf` relationships (list entries carry
  a `[key='value']` predicate), then back to YANG with the faithfulness
  round-trip passing. Moves the L3SM evidence from schema to instances.
- Drift lifecycle demonstration (`src/run_drift.py`): a simulated far-side model
  change (a new leaf and a rename) is caught by both a translator novelty check
  and an ongoing round-trip check, wakes the counterpart engine, and is resolved
  by incremental re-reconciliation of only the affected node, restoring both
  checks. Shows the cheap operational-plane sensing that triggers cognition, and
  that the costly step runs only on the delta.
- Model selection: `--model <id>` on the reconcile commands overrides the default
  (`OPENAI_MODEL` in `.env`), and `src/list_models.py` lists the model ids your
  account can see, to find a specific model's exact id.
- HTML demo movies (`src/make_demo.py`, `demo/*.html`): self-contained,
  dependency-free step-through pages for the instance round-trip and the drift
  lifecycle, generated from the run outputs, for hosting on a public repo and
  linking from the ID. Regenerate with `python3 src/make_demo.py` after running
  `run_instance.py` and `run_drift.py`.

## The argument

draft-lls-onsen-yang-tmf-mapping motivates a standardized YANG-to-TMF mapping by
the cost of hand-built adapters: TMF clients need custom adapters to consume
YANG-modeled interfaces, models drift in identity, constraints and defaults, and
one-off adapters are expensive to maintain. Where the two systems are cognitive
agents, that cost collapses. A YANG-side agent and a TMF-side agent reconcile
from their own models plus a thin shared reference lexicon, emit a deterministic
translator, and regenerate it when a model moves, with an auditable record of
each decision. What remains worth standardizing is the thin identity anchor, not
the adapter.

## How it is scored

The agents never see the draft's mapping specification. The translator they emit
is scored two ways:

1. **Faithfulness** (self-checking, no oracle): YANG instance to TMF to YANG
   instance returns the original. The adapter works.
2. **Equivalence** (oracle = the reference mapper): the agents' TMF output
   matches what the draft's rules prescribe. The standard was unnecessary for
   the mapping itself.

## Stages

- **Stage 0 (done):** deterministic reference mapper, validated on the draft's
  toaster example. No API cost.
- **Stage 1:** agent-to-agent reconciliation harness. Runs with the user's own
  API licence. Records transcripts for offline replay.
- **Stage 2:** scale to L3SM (RFC 8299) and score faithfulness and equivalence.
- **Stage 3:** wrap as a shared live demonstrator with a recording. Offline
  replay from recorded transcripts; live mode with a user-supplied API key.

## Run Stage 0

    cd ~/Downloads/onsen-reconciliation-demonstrator
    pip install --break-system-packages -r requirements.txt
    python3 src/run_toaster.py

Expected final line: `PASS`.

## Run Stage 1

Plumbing check, no key, no cost (also demonstrates interrupt/resume):

    cd ~/Downloads/onsen-reconciliation-demonstrator
    python3 src/run_reconcile.py --provider mock --run-id toaster-mock

Live run on your OpenAI licence. Write your key into `.env` first:

    cd ~/Downloads/onsen-reconciliation-demonstrator
    printf 'OPENAI_API_KEY=%s\nOPENAI_MODEL=%s\n' "PASTE_YOUR_OPENAI_KEY_HERE" "gpt-4o" > .env
    python3 src/run_reconcile.py --provider openai --run-id toaster-live

If a run is interrupted, continue it with no repeated spend:

    cd ~/Downloads/onsen-reconciliation-demonstrator
    python3 src/run_reconcile.py --provider openai --run-id toaster-live --resume

Two scores print at the end: `faithfulness round-trip` and `equivalence vs
oracle`. Both `PASS` means the agents built the standard's mapping on their own.

## Run Stage 2 (L3SM)

The full L3SM service model (RFC 8299 `vpn-service` and `site`), 90 nodes and
209 characteristics, reconciled node by node over N independent trials to measure
how reliably the agents reproduce the standard mapping.

Plumbing check, no key, no cost:

    cd ~/Downloads/onsen-reconciliation-demonstrator
    .venv/bin/python src/reconcile_l3sm.py --provider mock --run-id l3sm-mock --trials 2

Live big run on your OpenAI licence. Each trial is 180 calls, about $0.60 and 5
to 7 minutes, so 8 trials is roughly $5 and 45 to 75 minutes:

    cd ~/Downloads/onsen-reconciliation-demonstrator
    .venv/bin/python src/reconcile_l3sm.py --provider openai --run-id l3sm-full --trials 8

Resume after an interruption, no repeated spend:

    cd ~/Downloads/onsen-reconciliation-demonstrator
    .venv/bin/python src/reconcile_l3sm.py --provider openai --run-id l3sm-full --trials 8 --resume

Set `--trials` to match your time: 3 for a ~20 minute look, 8 for breakfast, more
if you want. The run writes `out/l3sm-full-result.json` with the convergence rate
(how many of the N trials reproduced the standard mapping exactly across all 209
characteristics) and, per leaf, where the agents diverged. Drag that file in.

## Run the instance demonstration (operational concrete)

A real L3SM `vpn-service` instance, YANG to TMF and back, no key, no cost:

    cd ~/Downloads/onsen-reconciliation-demonstrator
    .venv/bin/python src/run_instance.py

Prints the nested TMF Service (features with `composedOf`, list entries with
`[key='value']` predicates) and the faithfulness round-trip result, and writes
`out/l3sm-instance-result.json`.

## Run the drift demonstration

The model-change lifecycle (detect, trigger, incrementally re-reconcile,
verify), no key, no cost:

    cd ~/Downloads/onsen-reconciliation-demonstrator
    .venv/bin/python src/run_drift.py

## Run the service-to-network case (L3SM to L3NM)

The cross-abstraction case: interrogation, pragmatics, self-maintenance and a
virtual experiment, over-arching against both-cognitive.

Plumbing check, no key, no cost:

    cd ~/Downloads/onsen-reconciliation-demonstrator
    .venv/bin/python src/reconcile_sn.py --provider mock --run-id sn-mock

Live run on your OpenAI licence (a few calls, seconds, well under a cent):

    cd ~/Downloads/onsen-reconciliation-demonstrator
    caffeinate -is .venv/bin/python src/reconcile_sn.py --provider openai --run-id sn-live

Writes `out/sn-live-result.json` and records `transcripts/sn-live.jsonl`.

## Layout

    models/yang/   ietf-l3vpn-svc.yang, ietf-l3vpn-ntw-extract.yang, ietf-yang-tmf-map.yang
    src/           reconcile_l3sm.py, reconcile_sn.py, run_drift.py, reference_mapper.py (oracle)
    fixtures/      sample YANG instance data
    demo-movies/   reconciliation-live.html (step-through demonstrator movie)
    out/           run result files
    transcripts/   recorded runs, for offline replay

## Notes

- `example-toaster.yang` is a faithful stand-in, not a transcription of the
  draft's printed module. Drop in the draft's exact module to diff generated
  payloads against the draft's Appendix verbatim.
- Licensed Apache-2.0.
