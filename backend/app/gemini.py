"""Gemini client (CR-018). The key stays server-side: read from backend/.env, never logged or returned."""
from __future__ import annotations

import functools
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

log = logging.getLogger(__name__)

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)

TEMPERATURE = 0.2
TIMEOUT_MS = 15_000

_thinking_supported = True


def api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY", "").strip() or None


def model_name() -> str | None:
    return os.environ.get("GEMINI_MODEL", "").strip() or None


def configured() -> bool:
    return bool(api_key() and model_name())


@functools.lru_cache(maxsize=1)
def client() -> genai.Client:
    # One attempt per call: the chat has its own 15 s budget and a deterministic fallback.
    return genai.Client(
        api_key=api_key(),
        http_options=types.HttpOptions(timeout=TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1)),
    )


def _thinking(model: str) -> types.ThinkingConfig | None:
    """Least thinking the model allows: it is the biggest latency cost for Flash models."""
    if not _thinking_supported:
        return None
    name = model.lower()
    if "2.5" in name:
        return types.ThinkingConfig(thinking_budget=0) if "flash" in name else None
    return types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)


def generate(contents: list, *, system: str, tools: list | None = None, force_text: bool = False,
             timeout_ms: int = TIMEOUT_MS, temperature: float = TEMPERATURE) -> types.GenerateContentResponse:
    """One generate_content call with the house settings. Raises on any API error."""
    global _thinking_supported
    model = model_name()
    if not model or not api_key():
        raise RuntimeError("Gemini is not configured (GEMINI_API_KEY / GEMINI_MODEL in backend/.env)")

    def config() -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            tools=tools,
            tool_config=(types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="NONE"))
                         if force_text and tools else None),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=_thinking(model),
            http_options=types.HttpOptions(timeout=max(1000, int(timeout_ms)),
                                           retry_options=types.HttpRetryOptions(attempts=1)),
        )

    try:
        return client().models.generate_content(model=model, contents=contents, config=config())
    except Exception as exc:  # noqa: BLE001
        # Some models reject a thinking level; drop it once for the whole process and retry.
        if _thinking_supported and "thinking" in str(exc).lower():
            log.warning("model %s rejected the thinking config; retrying without it", model)
            _thinking_supported = False
            return client().models.generate_content(model=model, contents=contents, config=config())
        raise
