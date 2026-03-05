"""
Shared Groq client, model constant, and retry logic.
Imported by proposal_generator.py, qualifier.py, and builder.py.

Switched from Cerebras to Groq to avoid 429 rate limits.
The Groq SDK mirrors the OpenAI interface so all callers
continue to work without changes.
"""
import os
import time
import random
import logging
from groq import (
    Groq,
    BadRequestError,
    APIStatusError,
    APIConnectionError,
    RateLimitError,
)

log = logging.getLogger(__name__)

MODEL = "llama-3.3-70b-versatile"

_client: Groq | None = None


def get_client() -> Groq:
    """Return a lazily-initialised Groq singleton.
    max_retries=0 so our own retry loop (call_with_retry) is in full control."""
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to your Railway env vars.")
        _client = Groq(api_key=api_key, max_retries=0)
    return _client


def call_with_retry(fn, *, max_retries: int = 4):
    """
    Call fn() and retry on RateLimitError (HTTP 429) with exponential backoff.

    Delays: ~1s, ~2s, ~4s, ~8s between attempts (plus ±1s jitter).
    All other exceptions propagate immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except RateLimitError as e:
            if attempt == max_retries:
                log.error("Groq rate limit hit — no retries left, giving up.")
                raise
            wait = (2 ** attempt) + random.uniform(0, 1)
            log.warning(
                "Groq rate limit (429) — retrying in %.1fs (attempt %d/%d)…",
                wait, attempt + 1, max_retries,
            )
            time.sleep(wait)


# Re-export exceptions so callers only need one import line
__all__ = [
    "MODEL",
    "get_client",
    "call_with_retry",
    "BadRequestError",
    "APIStatusError",
    "APIConnectionError",
    "RateLimitError",
]
