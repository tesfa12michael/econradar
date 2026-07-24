"""LLMService — multi-provider narration/Q&A rotation (feature 1.5, Phase 3).

Fallback rotation (authoritative — see architecture.md decision #7):
    Mistral (narration)  →  Groq (speed/Q&A)  →  OpenRouter (final fallback)
Do NOT reorder without updating docs/architecture.md.

Groundedness rule (architecture.md decision #8): the LLM only narrates precomputed
numbers — it must never generate, estimate, or approximate a statistic. The
groundedness verifier that enforces this is implemented alongside narrate() in Phase 3.
"""

from __future__ import annotations

from typing import ClassVar


class LLMService:
    PROVIDER_ORDER: ClassVar[tuple[str, ...]] = ("mistral", "groq", "openrouter")

    async def narrate(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "LLM narration lands in Phase 3 (feature 1.5). "
            "Provider order is fixed here: " + " -> ".join(self.PROVIDER_ORDER)
        )

    async def answer(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("RAG Q&A lands in Phase 3 (feature 2.2).")
