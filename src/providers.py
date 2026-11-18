"""LLM provider abstraction.

Two providers:
  * OpenAIProvider : real calls, key and model from the environment (.env).
  * MockProvider   : deterministic canned replies, no network, no cost. Used to
                     validate the harness plumbing (checkpointing, resume,
                     scoring) without spending anything.

Each call returns an LLMResult carrying the text plus token usage, so the
negotiator can meter cumulative tokens and estimate cost.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    model: str


class MockProvider:
    """Returns canned replies keyed by a 'step' tag in the request.

    The replies are intentionally correct so the end-to-end pipeline and the
    resume machinery can be exercised offline. Real negotiation content comes
    from OpenAIProvider.
    """

    model = "mock"

    def __init__(self, canned: dict[str, str]):
        self._canned = canned

    def complete(self, step: str, system: str, user: str) -> LLMResult:
        t0 = time.time()
        text = self._canned.get(step, "{}")
        return LLMResult(
            text=text,
            prompt_tokens=len(system) // 4 + len(user) // 4,
            completion_tokens=len(text) // 4,
            seconds=time.time() - t0,
            model=self.model,
        )


class OpenAIProvider:
    def __init__(self, model: str | None = None):
        from openai import OpenAI  # imported lazily so mock runs need no key
        self._client = OpenAI()  # reads OPENAI_API_KEY from env
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o")

    def complete(self, step: str, system: str, user: str) -> LLMResult:
        t0 = time.time()
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        usage = resp.usage
        return LLMResult(
            text=resp.choices[0].message.content or "",
            prompt_tokens=getattr(usage, "prompt_tokens", 0),
            completion_tokens=getattr(usage, "completion_tokens", 0),
            seconds=time.time() - t0,
            model=self.model,
        )


# Rough public price table (USD per 1M tokens). Estimates only; the harness
# prints the model so you can correct these. Update freely.
PRICE_PER_MTOK = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "o3": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    key = model
    if key not in PRICE_PER_MTOK:
        # try a prefix match (e.g. dated model ids)
        for k in PRICE_PER_MTOK:
            if model.startswith(k):
                key = k
                break
    if key not in PRICE_PER_MTOK:
        return None
    pin, pout = PRICE_PER_MTOK[key]
    return prompt_tokens / 1e6 * pin + completion_tokens / 1e6 * pout
