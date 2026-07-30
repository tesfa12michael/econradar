"""LLMService — multi-provider narration/Q&A rotation (feature 1.5, Phase 3).

Fallback rotation (authoritative — see architecture.md decision #7):
    Mistral (narration)  →  Groq (speed/Q&A)  →  OpenRouter (final fallback)
Do NOT reorder without updating docs/architecture.md.

**Task routing, not reordering** (decision #24). The rotation above is one ordered
list. A task may nominate which member it *starts* at — narration starts at Mistral,
RAG Q&A starts at Groq for latency, exactly as the stack table describes — after
which the remaining providers are tried in the rotation's own order, so OpenRouter
stays the final fallback in every case.

**Groundedness is part of the call, not a step after it** (decision #8). A
completion that cites a number it was not given is treated as a provider failure
and hands over to the next provider, the same as a timeout. That is the whole
point: an ungrounded narration must be *impossible to serve*, not merely scored.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from config import settings
from logging_config import get_logger
from services import providers
from services.groundedness import GroundednessReport, verify
from services.providers import (
    Completion,
    ProviderError,
    ProviderNotConfigured,
    ProviderRateLimited,
)

logger = get_logger(__name__)


class NarrationUnavailable(RuntimeError):
    """No provider produced a grounded response."""


@dataclass(frozen=True, slots=True)
class GroundedCompletion:
    text: str
    provider: str
    model: str
    groundedness: GroundednessReport
    token_count: int | None = None
    attempts: tuple[str, ...] = ()


class LLMService:
    PROVIDER_ORDER: ClassVar[tuple[str, ...]] = ("mistral", "groq", "openrouter")

    def rotation_for(self, primary: str | None = None) -> tuple[str, ...]:
        """The rotation, optionally started at `primary`.

        The tail keeps the documented order, so OpenRouter is last however the list
        is entered. A primary that is not in the rotation is ignored rather than
        prepended — the rotation is the contract.
        """
        if primary is None or primary not in self.PROVIDER_ORDER:
            return self.PROVIDER_ORDER
        return (primary, *(p for p in self.PROVIDER_ORDER if p != primary))

    def available(self, primary: str | None = None) -> list[str]:
        return providers.configured_providers(self.rotation_for(primary))

    async def generate(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        context: Any,
        primary: str | None = None,
        require_grounded: bool = True,
    ) -> GroundedCompletion:
        """Walk the rotation until a provider returns a grounded completion.

        `context` is the object the narration was built from — the verifier matches
        every number in the response against it, so passing a context that does not
        contain the supplied numbers will (correctly) fail everything.
        """
        if not settings.llm_enabled:
            raise NarrationUnavailable("LLM calls are disabled (LLM_ENABLED=false).")

        order = self.rotation_for(primary)
        configured = providers.configured_providers(order)
        if not configured:
            raise NarrationUnavailable(
                "no LLM provider is configured — set MISTRAL_API_KEY, GROQ_API_KEY "
                "or OPENROUTER_API_KEY"
            )

        attempts: list[str] = []
        for provider in configured:
            try:
                completion = await providers.complete_openai_compatible(provider, messages)
            except ProviderRateLimited as exc:
                # Logged distinctly: features.md 1.5 requires rate-limit fallback be
                # observable, and "rate limited" and "broken" need different responses.
                attempts.append(f"{provider}: rate limited")
                logger.warning("LLM rotation: %s rate limited, falling back — %s", provider, exc)
                continue
            except (ProviderNotConfigured, ProviderError) as exc:
                attempts.append(f"{provider}: {exc}")
                logger.warning("LLM rotation: %s failed, falling back — %s", provider, exc)
                continue

            report = verify(completion.text, context)
            if require_grounded and not report.passed:
                attempts.append(f"{provider}: ungrounded ({report.reason()})")
                logger.warning(
                    "LLM rotation: %s produced ungrounded output (score=%.2f, %s) — discarding",
                    provider,
                    report.score,
                    report.reason(),
                )
                continue

            if attempts:
                logger.info("LLM rotation settled on %s after: %s", provider, "; ".join(attempts))
            return GroundedCompletion(
                text=completion.text,
                provider=completion.provider,
                model=completion.model,
                groundedness=report,
                token_count=completion.token_count,
                attempts=tuple(attempts),
            )

        raise NarrationUnavailable(
            "every provider failed or produced ungrounded output: " + "; ".join(attempts)
        )

    async def narrate(
        self, messages: Sequence[dict[str, Any]], *, context: Any
    ) -> GroundedCompletion:
        """Narration path — starts at Mistral (decision #7's primary)."""
        return await self.generate(messages, context=context, primary="mistral")

    async def answer(
        self, messages: Sequence[dict[str, Any]], *, context: Any
    ) -> GroundedCompletion:
        """RAG Q&A path — starts at Groq, the speed layer (feature 2.2)."""
        return await self.generate(messages, context=context, primary="groq")

    def stream_answer(self, messages: Sequence[dict[str, Any]], *, provider: str = "groq") -> Any:
        """Raw token stream for the chat UI.

        Returns the provider's async iterator directly. The caller **must** verify
        groundedness on the reassembled text before treating the answer as final —
        a fabricated figure can straddle two deltas, so a per-chunk check would miss it.
        """
        return providers.stream_openai_compatible(provider, messages)


def completion_to_grounded(completion: Completion, context: Any) -> GroundedCompletion:
    """Wrap an already-obtained completion with its groundedness report.

    Used by `VLMService`, whose rotation is Gemini -> Qwen3-VL rather than this
    class's, but whose output is held to the same standard.
    """
    return GroundedCompletion(
        text=completion.text,
        provider=completion.provider,
        model=completion.model,
        groundedness=verify(completion.text, context),
        token_count=completion.token_count,
    )
