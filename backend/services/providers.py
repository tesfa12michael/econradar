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
    # The same host as `mistral`, registered separately because it runs a different
    # model: the agent needs one that can choose tools, narration does not.
    "mistral_agent": "https://api.mistral.ai/v1/chat/completions",
    "nvidia_nim": "https://integrate.api.nvidia.com/v1/chat/completions",
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
        "mistral_agent": settings.mistral_api_key,
        "nvidia_nim": settings.nvidia_nim_api_key,
        "groq": settings.groq_api_key,
        "openrouter": settings.openrouter_api_key,
        "gemini_flash": settings.google_api_key,
        "qwen3_vl_dashscope": settings.qwen_api_key,
    }.get(provider)


def model_for(provider: str) -> str:
    return {
        "mistral": settings.mistral_model,
        "mistral_agent": settings.mistral_agent_model,
        "nvidia_nim": settings.nvidia_nim_model,
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


# ── Tool calling (the agent, decision #38) ───────────────────────────────────
#
# Three providers, two wire formats, one neutral conversation. Mistral and NVIDIA
# NIM speak the OpenAI `tools`/`tool_calls` shape; Gemini speaks
# `functionDeclarations`/`functionCall`/`functionResponse` and has no notion of a
# tool-call id at all. Rather than let either shape leak into the agent, the loop
# builds a list of `AgentTurn` and each adapter converts it on the way out. A
# provider swap is then a converter, not a rewrite of the graph.


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    #: Gemini 3.x returns an opaque `thoughtSignature` on the part carrying a
    #: function call, and **rejects the next turn with HTTP 400 if it is not sent
    #: back** ("Function call is missing a thought_signature… required for tools to
    #: work correctly"). So it is not optional metadata: without it the Gemini
    #: fallback fails on the second step of every question that used a tool, which
    #: is every question. Found live, on the first fallback that actually fired.
    #: The other providers have no equivalent and ignore it.
    signature: str | None = None


@dataclass(frozen=True, slots=True)
class AgentTurn:
    """One step of the conversation, in neither provider's dialect.

    `role` is "user", "assistant" or "tool". An assistant turn carries text, tool
    calls, or both; a tool turn carries the result of exactly one call.
    """

    role: str
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCompletion:
    """What a provider returned: prose, tool calls, or both."""

    text: str
    tool_calls: tuple[ToolCall, ...]
    provider: str
    model: str
    token_count: int | None = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


def _decode_arguments(raw: Any) -> dict[str, Any]:
    """Tool arguments, however the provider spelled them.

    OpenAI-shaped providers send a JSON *string*; Gemini sends an object. A model
    can also send malformed JSON, and that has to degrade to an empty argument set
    rather than raising — the tool will then report what it needed, which the model
    can act on, instead of the whole turn failing.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("tool arguments were not valid JSON: %s", raw[:120])
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


#: Content-part types that are the model's reasoning rather than its answer.
#: Concatenating them would put the scratchpad in front of a reader *and* feed the
#: verifier numbers the model was only considering — the same reason Gemini's
#: `thought` parts are filtered (PROGRESS.md lesson 13).
_REASONING_PART_TYPES = frozenset({"thinking", "reasoning", "thought"})


def _content_text(content: Any) -> str:
    """The assistant's prose, whether the provider sent a string or content parts.

    Mistral's chat API returns `content` as a *list* of typed chunks once tool
    calling is in play, and reading `.strip()` off it is an AttributeError rather
    than an empty answer — found live on the first agent run, not in a fixture.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        pieces: list[str] = []
        for part in content:
            if isinstance(part, str):
                pieces.append(part)
            elif isinstance(part, dict) and part.get("type") not in _REASONING_PART_TYPES:
                text = part.get("text")
                if isinstance(text, str):
                    pieces.append(text)
        return "".join(pieces).strip()
    return ""


def _to_openai_messages(system: str, turns: Sequence[AgentTurn]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for turn in turns:
        if turn.role == "tool":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": turn.tool_call_id,
                    "name": turn.tool_name,
                    "content": turn.text or "",
                }
            )
        elif turn.role == "assistant":
            message: dict[str, Any] = {"role": "assistant", "content": turn.text or ""}
            if turn.tool_calls:
                message["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        },
                    }
                    for call in turn.tool_calls
                ]
            messages.append(message)
        else:
            messages.append({"role": "user", "content": turn.text or ""})
    return messages


def _to_gemini_contents(turns: Sequence[AgentTurn]) -> list[dict[str, Any]]:
    """Gemini's `contents`, where a tool result is a *user* turn.

    Google models a function response as something the caller hands back, so it
    carries the `user` role even though no user wrote it. Getting this wrong makes
    the model re-issue the same call forever.
    """
    contents: list[dict[str, Any]] = []
    for turn in turns:
        if turn.role == "tool":
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": turn.tool_name,
                                # Gemini requires an object here, never a bare string.
                                "response": {"result": turn.text or ""},
                            }
                        }
                    ],
                }
            )
            continue
        parts: list[dict[str, Any]] = []
        if turn.text:
            parts.append({"text": turn.text})
        for call in turn.tool_calls:
            part: dict[str, Any] = {"functionCall": {"name": call.name, "args": call.arguments}}
            if call.signature:
                part["thoughtSignature"] = call.signature
            parts.append(part)
        if not parts:
            continue
        contents.append({"role": "model" if turn.role == "assistant" else "user", "parts": parts})
    return contents


async def complete_with_tools_openai(
    provider: str,
    system: str,
    turns: Sequence[AgentTurn],
    tools: Sequence[dict[str, Any]],
    *,
    model: str | None = None,
) -> ToolCompletion:
    """One agent step from an OpenAI-compatible provider (Mistral, NVIDIA NIM)."""
    key = api_key_for(provider)
    if not key:
        raise ProviderNotConfigured(f"{provider} has no API key configured")
    endpoint = OPENAI_COMPATIBLE_ENDPOINTS[provider]
    chosen = model or model_for(provider)

    body = {
        "model": chosen,
        "messages": _to_openai_messages(system, turns),
        "tools": list(tools),
        "tool_choice": "auto",
        "temperature": settings.llm_temperature,
        "max_tokens": settings.agent_max_tokens,
    }

    async with httpx.AsyncClient(timeout=settings.agent_timeout_seconds) as client:
        try:
            response = await client.post(endpoint, headers=_headers(provider, key), json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{provider} transport error: {type(exc).__name__}") from exc

    _raise_for_status(provider, response)
    payload = response.json()
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"{provider} returned an unexpected body shape") from exc

    calls = tuple(
        ToolCall(
            id=str(raw.get("id") or f"call_{index}"),
            name=(raw.get("function") or {}).get("name", ""),
            arguments=_decode_arguments((raw.get("function") or {}).get("arguments")),
        )
        for index, raw in enumerate(message.get("tool_calls") or [])
    )
    usage = payload.get("usage") or {}
    return ToolCompletion(
        text=_content_text(message.get("content")),
        tool_calls=tuple(c for c in calls if c.name),
        provider=provider,
        model=chosen,
        token_count=usage.get("total_tokens"),
    )


async def complete_with_tools_gemini(
    system: str,
    turns: Sequence[AgentTurn],
    tools: Sequence[dict[str, Any]],
    *,
    model: str | None = None,
) -> ToolCompletion:
    """One agent step from Gemini on the Agent Platform.

    `tools` arrives in the OpenAI shape and is translated here, so the agent
    declares its tools once rather than twice — two declarations of the same tool
    are two things to keep in step, and they would drift.
    """
    key = api_key_for("gemini_flash")
    if not key:
        raise ProviderNotConfigured("gemini_flash has no API key configured")
    chosen = model or model_for("gemini_flash")

    declarations = [
        {
            "name": tool["function"]["name"],
            "description": tool["function"].get("description", ""),
            "parameters": tool["function"].get("parameters", {}),
        }
        for tool in tools
    ]
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": _to_gemini_contents(turns),
        "tools": [{"functionDeclarations": declarations}],
        "generationConfig": {
            "temperature": settings.llm_temperature,
            "maxOutputTokens": settings.agent_max_tokens,
            "thinkingConfig": {"thinkingLevel": settings.gemini_thinking_level},
        },
    }

    async with httpx.AsyncClient(timeout=settings.agent_timeout_seconds) as client:
        try:
            response = await client.post(
                GEMINI_ENDPOINT.format(model=chosen),
                params={"key": key},
                headers={"Content-Type": "application/json"},
                json=body,
            )
        except httpx.HTTPError as exc:
            # Type only — an httpx error's str() carries the URL, and the URL carries
            # the key for this provider.
            raise ProviderError(f"gemini_flash transport error: {type(exc).__name__}") from exc

    _raise_for_status("gemini_flash", response)
    payload = response.json()
    candidate = (payload.get("candidates") or [{}])[0]
    if not candidate.get("content"):
        reason = (payload.get("promptFeedback") or {}).get("blockReason") or candidate.get(
            "finishReason"
        )
        raise ProviderError(f"gemini_flash returned no content{f' ({reason})' if reason else ''}")
    if candidate.get("finishReason") == "MAX_TOKENS":
        raise ProviderError("gemini_flash hit the output ceiling before finishing")

    parts = candidate["content"].get("parts", [])
    calls = tuple(
        # Gemini has no tool-call id, so one is synthesised. It is never sent back to
        # Google — only the OpenAI adapter uses ids — but the agent keys its results
        # on it, so it has to exist and be unique within the turn.
        ToolCall(
            id=f"gemini_{index}",
            name=part["functionCall"].get("name", ""),
            arguments=_decode_arguments(part["functionCall"].get("args")),
            # Carried straight back on the next request — see ToolCall.signature.
            signature=part.get("thoughtSignature"),
        )
        for index, part in enumerate(parts)
        if "functionCall" in part
    )
    text = "".join(part.get("text", "") for part in parts if not part.get("thought"))

    usage = payload.get("usageMetadata") or {}
    return ToolCompletion(
        text=text.strip(),
        tool_calls=tuple(c for c in calls if c.name),
        provider="gemini_flash",
        model=chosen,
        token_count=usage.get("totalTokenCount"),
    )


async def complete_with_tools(
    provider: str,
    system: str,
    turns: Sequence[AgentTurn],
    tools: Sequence[dict[str, Any]],
) -> ToolCompletion:
    """One agent step from whichever provider, in that provider's own dialect."""
    if provider == "gemini_flash":
        return await complete_with_tools_gemini(system, turns, tools)
    if provider in OPENAI_COMPATIBLE_ENDPOINTS:
        return await complete_with_tools_openai(provider, system, turns, tools)
    raise ProviderNotConfigured(f"{provider} has no tool-calling adapter")


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
