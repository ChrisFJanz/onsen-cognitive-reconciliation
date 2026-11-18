"""Checkpointed, resumable agent-to-agent reconciliation.

The negotiation is a sequence of steps, each one LLM call. Every completed step
is appended to transcripts/<run>.jsonl the instant it finishes. If the run is
interrupted (Ctrl-C, closed lid, lost network), restart with resume=True: the
saved steps are replayed with no API calls, then the run continues from the
first unfinished step. The same transcript drives offline replay in the shared
demonstrator.

Protocol (first cut, grounded in the two NMRG drafts):
  1. propose : a YANG-side agent, given its own reference lexicon and the TMF
     target conventions, proposes a mapping table (the translator).
  2. review  : a TMF-side agent checks the proposal against the TMF conventions
     and returns the final mapping table.

The agents are never shown the draft's mapping specification.
"""

from __future__ import annotations

import json
import os
import time
from typing import Callable

from providers import estimate_cost

TMF_CONVENTIONS = (
    "TMF target conventions: an annotated YANG container or list becomes a TMF "
    "Service or Resource specification; each leaf and leaf-list becomes a "
    "Characteristic. Map YANG base types to JSON Schema types: boolean to "
    "boolean, string/enumeration/identityref to string, integer types to "
    "integer, decimal64 to number; a leaf-list becomes the matching array type. "
    "Shared-reference naming anchor: a characteristic's name is the YANG node "
    "identifier taken verbatim from the reference lexicon term. Do not rename or "
    "change case; 'serial-number' stays 'serial-number', never 'serialNumber'."
)

PROPOSE_SYS = (
    "You are the YANG-side cognitive agent in an agent-to-agent model "
    "reconciliation. You know only your own YANG reference lexicon and the "
    "stated TMF target conventions. Propose a mapping table as JSON with keys "
    "'root' {yang_module, yang_path, tmf_type, tmf_name} and 'characteristics' "
    "(list of {yang_name, tmf_name, json_type}). Respond with JSON only."
)

REVIEW_SYS = (
    "You are the TMF-side cognitive agent. Check the proposed mapping table "
    "against the TMF target conventions and the YANG lexicon, fix any wrong "
    "json_type, any renamed characteristic (every tmf_name must equal the YANG "
    "node identifier verbatim, no case changes), and any missing characteristic, "
    "and return the final mapping table in the same JSON shape. Respond with "
    "JSON only."
)


class Negotiator:
    def __init__(self, provider, run_id: str, transcript_dir: str):
        self.provider = provider
        self.run_id = run_id
        os.makedirs(transcript_dir, exist_ok=True)
        self.path = os.path.join(transcript_dir, f"{run_id}.jsonl")
        self.done: dict[str, dict] = {}
        self.tot_prompt = 0
        self.tot_completion = 0
        self.tot_seconds = 0.0
        self.api_calls = 0

    def _load(self):
        if not os.path.exists(self.path):
            return
        with open(self.path) as fh:
            for line in fh:
                rec = json.loads(line)
                self.done[rec["step"]] = rec
        if self.done:
            print(f"[resume] replayed {len(self.done)} step(s) from "
                  f"{os.path.basename(self.path)}, 0 API calls")

    def _append(self, rec: dict):
        with open(self.path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _step(self, step: str, system: str, user: str) -> dict:
        if step in self.done:
            return self.done[step]
        res = self.provider.complete(step, system, user)
        self.api_calls += 1
        self.tot_prompt += res.prompt_tokens
        self.tot_completion += res.completion_tokens
        self.tot_seconds += res.seconds
        cost = estimate_cost(res.model, self.tot_prompt, self.tot_completion)
        cost_s = f"~${cost:.3f}" if cost is not None else "n/a"
        print(f"[step {step}] {res.seconds:5.1f}s  "
              f"tok {res.prompt_tokens}+{res.completion_tokens}  "
              f"cumulative {self.tot_seconds:5.1f}s {cost_s} ({res.model})")
        rec = {"step": step, "system": system, "user": user,
               "text": res.text, "prompt_tokens": res.prompt_tokens,
               "completion_tokens": res.completion_tokens,
               "seconds": res.seconds, "model": res.model,
               "ts": time.time()}
        self._append(rec)
        self.done[step] = rec
        return rec

    def run(self, yang_lex: list[dict], yang_module: str, resume: bool) -> dict:
        if resume:
            self._load()
        lex_json = json.dumps(yang_lex, indent=2)

        propose_user = (
            f"YANG module: {yang_module}\n"
            f"YANG reference lexicon:\n{lex_json}\n\n{TMF_CONVENTIONS}"
        )
        proposal = self._step("propose", PROPOSE_SYS, propose_user)

        review_user = (
            f"YANG module: {yang_module}\n"
            f"YANG reference lexicon:\n{lex_json}\n\n{TMF_CONVENTIONS}\n\n"
            f"Proposed mapping table:\n{proposal['text']}"
        )
        final = self._step("review", REVIEW_SYS, review_user)

        try:
            table = json.loads(final["text"])
        except json.JSONDecodeError as exc:
            raise SystemExit(f"final step did not return valid JSON: {exc}")
        return table

    def summary(self) -> str:
        cost = estimate_cost(self.provider.model, self.tot_prompt, self.tot_completion)
        cost_s = f"~${cost:.3f}" if cost is not None else "n/a"
        return (f"{self.api_calls} API call(s) this run, "
                f"{self.tot_seconds:.1f}s, "
                f"{self.tot_prompt}+{self.tot_completion} tokens, {cost_s}")
