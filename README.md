# ONSEN reconciliation demonstrator

## What's new

### 2026-11-19: explanatory note and videos, "Translation or binding"

With the mapping draft's annotations, the reasoner is correct on every specified
characteristic in 20 of 20 trials. Without them, it agrees on the service roots
in 3 of 10. Why that one decision cannot be reasoned out, while the rest of the
mapping can, is the subject of new explanatory material in
`translation-or-binding/`.

The automated reconciliation process can be hard to follow from the demonstrator
alone. A concept note and two narrated videos explain how the process handles
the two cases, TM Forum to L3SM and L3SM to L3NM, and why the handling must
differ, under a framework that distinguishes translation problems from binding
problems. Start with `translation-or-binding/README.md`.

A public demonstrator accompanying the Internet-Draft
draft-janz-onsen-cognitive-reconciliation. It shows that agent-to-agent
ontology reconciliation builds and maintains the YANG-to-TMF adapter that
draft-lls-onsen-yang-tmf-mapping sets out to standardize, and that for
cognitive systems building it is no burden.

Where the two systems are cognitive agents, the cost that motivates a single
standardized mapping collapses. A YANG-side agent and a TMF-side agent
reconcile from their own models plus a thin shared reference lexicon, emit a
deterministic translator, and regenerate it when a model moves, with an
auditable record of each decision. What remains worth standardizing is the thin
identity anchor and the boundary of authority over the contested cases, not the
adapter.

## The demonstrator movie

A single self-contained page walks the whole process end to end, each stage
marked for where it sits on the cognition-placement spectrum and whether more
cognition would add anything:

    demo-movies/reconciliation-live.html

Open it in any browser; it needs no server and no network. `demo-movies/` also
holds a short note on what the demonstrator is and how it was produced.

## How it is scored

The agents never see the draft's mapping specification. The translator they emit
is scored two ways:

1. **Faithfulness** (self-checking, no oracle): a YANG instance mapped to TMF
   and back returns the original. The adapter works.
2. **Equivalence** (oracle = the reference mapper in `src/reference_mapper.py`,
   which implements the draft's normative rules): the agents' TMF output matches
   what the draft's rules prescribe. The standard was unnecessary for the mapping
   itself.

## Getting set up

    git clone https://github.com/ChrisFJanz/onsen-cognitive-reconciliation
    cd onsen-cognitive-reconciliation
    pip install --break-system-packages -r requirements.txt

The mock-provider runs need no key and no cost. For a live run, supply your own
OpenAI licence once (the harness calls an ordinary mid-capability model; a
frontier model is not required):

    printf 'OPENAI_API_KEY=%s\nOPENAI_MODEL=%s\n' "PASTE_YOUR_OPENAI_KEY_HERE" "gpt-4o" > .env

Every live run checkpoints each step to `transcripts/<run>.jsonl`; `--resume`
replays saved steps with zero API calls and continues, so an interrupted run
loses at most the one call in flight. The recorded transcripts in `transcripts/`
let the published runs replay offline.

## Running the cases

**Reference-mapper proof** (deterministic, no key, no cost):

    python3 src/run_toaster.py

Expected final line: `PASS`.

**Schema-level reconciliation, L3SM** (RFC 8299 `vpn-service` and `site`, 90
nodes and 209 characteristics, reconciled node by node over N independent
trials). Plumbing check first:

    python3 src/reconcile_l3sm.py --provider mock --run-id l3sm-mock --trials 2

Live run on your OpenAI licence (each trial is about 90 calls, roughly $0.14 and
a few minutes; set `--trials` to match your time):

    python3 src/reconcile_l3sm.py --provider openai --run-id l3sm-full --trials 20

Writes `out/l3sm-full-result.json` with the convergence rate and, per leaf, where
the agents diverged.

**Instance round-trip** (a real L3SM `vpn-service` instance, YANG to TMF and
back, no key, no cost):

    python3 src/run_instance.py

Writes `out/l3sm-instance-result.json`.

**Drift lifecycle** (detect, trigger, incrementally re-reconcile, verify;
reactive events plus a measured proactive-notification gain). Plumbing check:

    python3 src/run_drift.py --provider mock --run-id drift-mock

Live run on your OpenAI licence (a few calls, seconds):

    python3 src/run_drift.py --provider openai --run-id drift-live

Writes `out/drift-live-result.json`.

**Service-to-network case** (L3SM to L3NM, RFC 8299 to RFC 9182: the
cross-abstraction pole, exercising interrogation, pragmatics, self-maintenance
and a virtual experiment against the over-arching placement). Plumbing check:

    python3 src/reconcile_sn.py --provider mock --run-id sn-mock

Live run (a few calls, seconds, well under a cent):

    python3 src/reconcile_sn.py --provider openai --run-id sn-live

Writes `out/sn-live-result.json`.

`--model <id>` on the reconcile commands overrides the default `OPENAI_MODEL`;
`src/list_models.py` lists the model ids your account can see.

## Layout

    models/yang/   ietf-l3vpn-svc.yang, ietf-l3vpn-ntw-extract.yang, ietf-yang-tmf-map.yang
    src/           reconcile_l3sm.py, reconcile_sn.py, run_drift.py, run_instance.py,
                   run_toaster.py, reference_mapper.py (oracle), providers.py
    fixtures/      sample YANG instance data
    demo-movies/   reconciliation-live.html (the demonstrator movie) and a note on it
    translation-or-binding/   concept note, two narrated videos and their transcripts
    out/           run result files
    transcripts/   recorded runs, for offline replay

## Notes

- `example-toaster.yang` is a faithful stand-in, not a transcription of the
  draft's printed module.
- Licensed Apache-2.0.
