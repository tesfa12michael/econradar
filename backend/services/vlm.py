"""VLMService — chart-to-narrative vision pipeline (feature 2.1, Phase 3).

Fallback order (authoritative — see architecture.md decision #9):
    Gemini Flash (Google Agent Platform)  →  Qwen3-VL (via DashScope)
Do NOT reorder without updating docs/architecture.md. The hosts in brackets are
transport and have both moved once (decision #28); the *order* has not.

The pipeline renders a chart to PNG server-side (`services/chart_render.py`) and
sends the image to the VLM; the same groundedness discipline as text narration
applies, and for the same reason it matters more here rather than less. A vision
model reading values off rendered axis labels will misread them — and then state
them with the confidence of something it "saw". So the prompt tells it to describe
the picture but take every figure from the data block, and the verifier checks the
result against that block exactly as it does for narration.
"""

from __future__ import annotations

from typing import Any, ClassVar

from config import settings
from logging_config import get_logger
from services import prompts, providers
from services.groundedness import verify
from services.llm import GroundedCompletion, NarrationUnavailable
from services.providers import (
    ProviderError,
    ProviderNotConfigured,
    ProviderRateLimited,
)

logger = get_logger(__name__)


class VLMService:
    PROVIDER_ORDER: ClassVar[tuple[str, ...]] = ("gemini_flash", "qwen3_vl_dashscope")

    def available(self) -> list[str]:
        return providers.configured_providers(self.PROVIDER_ORDER)

    async def interpret(
        self,
        prompt: str,
        image_b64: str,
        *,
        context: Any,
        system: str | None = None,
        require_grounded: bool = True,
    ) -> GroundedCompletion:
        """Interpret a chart image, walking the two-provider order.

        Gemini and Qwen3-VL take different request shapes — `contents[].parts[]`
        versus OpenAI-style content arrays — so the dispatch is explicit here rather
        than hidden behind a common signature that would only ever have two cases.

        `system` defaults to the grounded system prompt rather than to nothing. The
        text rotation gets it via `prompts.chat_messages`; a vision model reading
        figures off pixels needs it more, not less, so omission must not be possible
        by accident (decision #29).
        """
        system_text = prompts.system_prompt() if system is None else system
        if not settings.llm_enabled:
            raise NarrationUnavailable("VLM calls are disabled (LLM_ENABLED=false).")

        configured = self.available()
        if not configured:
            raise NarrationUnavailable(
                "no VLM provider is configured — set GOOGLE_AGENT_PLATFORM_API_KEY or QWEN_API_KEY"
            )

        attempts: list[str] = []
        for provider in configured:
            try:
                if provider == "gemini_flash":
                    completion = await providers.complete_gemini(
                        prompt, image_b64=image_b64, system=system_text
                    )
                else:
                    completion = await providers.complete_vision_qwen(
                        prompt, image_b64, system=system_text
                    )
            except ProviderRateLimited as exc:
                attempts.append(f"{provider}: rate limited")
                logger.warning("VLM order: %s rate limited, falling back — %s", provider, exc)
                continue
            except (ProviderNotConfigured, ProviderError) as exc:
                attempts.append(f"{provider}: {exc}")
                logger.warning("VLM order: %s failed, falling back — %s", provider, exc)
                continue

            report = verify(completion.text, context)
            if require_grounded and not report.passed:
                attempts.append(f"{provider}: ungrounded ({report.reason()})")
                logger.warning(
                    "VLM order: %s described figures not in the data block (%s) — discarding",
                    provider,
                    report.reason(),
                )
                continue

            if attempts:
                logger.info("VLM order settled on %s after: %s", provider, "; ".join(attempts))
            return GroundedCompletion(
                text=completion.text,
                provider=completion.provider,
                model=completion.model,
                groundedness=report,
                token_count=completion.token_count,
                attempts=tuple(attempts),
            )

        raise NarrationUnavailable(
            "every VLM provider failed or produced ungrounded output: " + "; ".join(attempts)
        )
