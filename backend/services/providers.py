"""HTTP clients for every LLM and VLM provider (features 1.5, 2.1, 2.2).

Raw `httpx` rather than four vendor SDKs. Mistral, Groq and OpenRouter all speak
the OpenAI chat-completions shape, so one function covers three providers, and the
alternative would put three more dependency trees on a 1 vCPU / 2 GB box to send
the same JSON. Gemini is the one genuinely different wire format and gets its own
adapter. Qwen3-VL joined the compatible group when it moved off OpenRouter onto
DashScope, which also speaks the OpenAI shape (decision #28).

Failures are typed by what the caller should *do* about them, not by what went
wrong: `ProviderRateLimited` and `ProviderError` both mean "move to the next
provider", and they are distinguished only so the rate-limit path is separately
observable — features.md 1.5 requires that fallback-on-rate-limit be logged.

No API key is ever logged, included in an exception message, or echoed back.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from config import settings
from logging_config import get_logger

logger = get_logger(__name__)

# ── Provider registry ────────────────────────────────────────────────────────

OPENAI_COMPATIBLE_ENDPOINTS: dict[str, str] = {
    "mistral": "https://api.mistral.ai/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    # Qwen3-VL direct from Alibaba's DashScope, OpenAI-compatible mode. The `-intl`
    # host is the one that accepts an international key; the Beijing host answers 401
    # for the same credential.
    "qwen3_vl_dashscope": (
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
    ),
}

# Vertex AI — renamed "Agent Platform" — rather than AI Studio. The two hosts take
# the same request body but not the same credentials: an Agent Platform key is
# rejected by generativelanguage.googleapis.com with HTTP 403 PERMISSION_DENIED.
# The key travels as a query parameter here, not the x-goog-api-key header.
GEMINI_ENDPOINT = (
    "https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent"
)


class ProviderError(RuntimeError):
    """A provider could not answer. The caller should try the next one."""


class ProviderRateLimited(ProviderError):
    """A provider refused with HTTP 429 or an explicit quota message."""


class ProviderNotConfigured(ProviderError):
    """No API key for this provider — it is skipped, not retried."""


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    provider: str
    model: str
    token_count: int | None = None


def api_key_for(provider: str) -> str | None:
    return {
        "mistral": settings.mistral_api_key,
        "groq": settings.groq_api_key,
        "openrouter": settings.openrouter_api_key,
        "gemini_flash": settings.google_api_key,
        "qwen3_vl_dashscope": settings.qwen_api_key,
    }.get(provider)


def model_for(provider: str) -> str:
    return {
        "mistral": settings.mistral_model,
        "groq": settings.groq_model,
        "openrouter": settings.openrouter_model,
        "gemini_flash": settings.gemini_model,
        "qwen3_vl_dashscope": settings.qwen_vlm_model,
    }[provider]


def configured_providers(order: Sequence[str]) -> list[str]:
    """The subset of `order` that has a key, preserving the documented order."""
    return [p for p in order if api_key_for(p)]


def _headers(provider: str, key: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        # OpenRouter attributes free-tier traffic to a referring app; omitting these
        # is allowed but lands the request in a stricter bucket.
        headers["HTTP-Referer"] = "https://econradar.vercel.app"
        headers["X-Title"] = "EconRadar"
    return headers


def _raise_for_status(provider: str, response: httpx.Response) -> None:
    if response.status_code == 429:
        raise ProviderRateLimited(f"{provider} rate limited (HTTP 429)")
    if response.status_code >= 400:
        # Body, not headers — headers carry the key.
        detail = response.text[:300].replace("\n", " ")
        if response.status_code in (401, 403):
            raise ProviderError(
                f"{provider} rejected the credentials (HTTP {response.status_code})"
            )
        raise ProviderError(f"{provider} HTTP {response.status_code}: {detail}")


def _openai_body(
    messages: Sequence[dict[str, Any]], model: str, *, stream: bool = False
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": list(messages),
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
        **({"stream": True} if stream else {}),
    }


async def complete_openai_compatible(
    provider: str, messages: Sequence[dict[str, Any]], *, model: str | None = None
) -> Completion:
    """One chat completion from Mistral, Groq, OpenRouter, or Qwen3-VL via DashScope."""
    key = api_key_for(provider)
    if not key:
        raise ProviderNotConfigured(f"{provider} has no API key configured")

    endpoint = OPENAI_COMPATIBLE_ENDPOINTS.get(provider, OPENAI_COMPATIBLE_ENDPOINTS["openrouter"])
    chosen = model or model_for(provider)

    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        try:
            response = await client.post(
                endpoint, headers=_headers(provider, key), json=_openai_body(messages, chosen)
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{provider} transport error: {type(exc).__name__}") from exc

    _raise_for_status(provider, response)
    payload = response.json()
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"{provider} returned an unexpected body shape") from exc
    if not text or not text.strip():
        raise ProviderError(f"{provider} returned empty content")

    usage = payload.get("usage") or {}
    return Completion(
        text=text.strip(),
        provider=provider,
        model=chosen,
        token_count=usage.get("total_tokens"),
    )


async def stream_openai_compatible(
    provider: str, messages: Sequence[dict[str, Any]], *, model: str | None = None
) -> AsyncIterator[str]:
    """Token deltas from an OpenAI-compatible provider (feature 2.2's speed layer).

    Yields text fragments. The caller reassembles them — and, critically, must run
    the groundedness check on the *reassembled* answer, because a fabricated number
    can be split across two deltas.
    """
    key = api_key_for(provider)
    if not key:
        raise ProviderNotConfigured(f"{provider} has no API key configured")
    endpoint = OPENAI_COMPATIBLE_ENDPOINTS.get(provider, OPENAI_COMPATIBLE_ENDPOINTS["openrouter"])
    chosen = model or model_for(provider)

    async with (
        httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client,
        client.stream(
            "POST",
            endpoint,
            headers=_headers(provider, key),
            json=_openai_body(messages, chosen, stream=True),
        ) as response,
    ):
        if response.status_code >= 400:
            await response.aread()
            _raise_for_status(provider, response)
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0]["delta"].get("content")
            except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                continue
            if delta:
                yield delta


async def complete_gemini(
    prompt: str,
    *,
    image_b64: str | None = None,
    model: str | None = None,
    system: str | None = None,
) -> Completion:
    """Gemini Flash on Google's Agent Platform — the VLM primary (decision #9).

    Google's wire format is `contents[].parts[]` rather than `messages[]`, and the
    key travels as a query parameter rather than an Authorization bearer.
    """
    key = api_key_for("gemini_flash")
    if not key:
        raise ProviderNotConfigured("gemini_flash has no API key configured")
    chosen = model or model_for("gemini_flash")

    parts: list[dict[str, Any]] = [{"text": prompt}]
    if image_b64:
        parts.append({"inline_data": {"mime_type": "image/png", "data": image_b64}})

    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": settings.llm_temperature,
            "maxOutputTokens": settings.gemini_max_output_tokens,
            "thinkingConfig": {"thinkingLevel": settings.gemini_thinking_level},
        },
    }
    if system:
        # Google's equivalent of the system role. Without it the groundedness rules
        # reach the model only as prose inside the user turn, which is measurably
        # weaker — see decision #29.
        body["systemInstruction"] = {"parts": [{"text": system}]}

    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        try:
            response = await client.post(
                GEMINI_ENDPOINT.format(model=chosen),
                params={"key": key},
                headers={"Content-Type": "application/json"},
                json=body,
            )
        except httpx.HTTPError as exc:
            # Deliberately only the exception type: an httpx error's str() carries the
            # request URL, and for this provider the URL carries the key.
            raise ProviderError(f"gemini_flash transport error: {type(exc).__name__}") from exc

    _raise_for_status("gemini_flash", response)
    payload = response.json()

    candidate = (payload.get("candidates") or [{}])[0]
    if not candidate.get("content"):
        # A safety block returns candidates without content — a real outcome, not a bug.
        reason = (payload.get("promptFeedback") or {}).get("blockReason") or candidate.get(
            "finishReason"
        )
        raise ProviderError(f"gemini_flash returned no content{f' ({reason})' if reason else ''}")
    if candidate.get("finishReason") == "MAX_TOKENS":
        # Reasoning ate the budget. A sentence cut off mid-figure can still satisfy the
        # verifier, so this hands over to the next provider instead of serving a stump.
        raise ProviderError("gemini_flash hit the output ceiling before finishing")
    # Reasoning parts are flagged `thought`. They are the model's scratchpad, not its
    # answer — concatenating them would show a reader the working and feed the
    # verifier numbers the model was only considering.
    text = "".join(
        part.get("text", "")
        for part in candidate["content"].get("parts", [])
        if not part.get("thought")
    )
    if not text.strip():
        raise ProviderError("gemini_flash returned empty content")

    usage = payload.get("usageMetadata") or {}
    return Completion(
        text=text.strip(),
        provider="gemini_flash",
        model=chosen,
        token_count=usage.get("totalTokenCount"),
    )


async def complete_vision_qwen(
    prompt: str, image_b64: str, *, system: str | None = None
) -> Completion:
    """Qwen3-VL through DashScope — the VLM fallback (decision #9, transport #28)."""
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                },
            ],
        }
    )
    return await complete_openai_compatible("qwen3_vl_dashscope", messages)
