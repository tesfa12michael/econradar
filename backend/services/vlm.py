"""VLMService — chart-to-narrative vision pipeline (feature 2.1, Phase 3).

Fallback order (authoritative — see architecture.md decision #9):
    Gemini Flash (Google AI Studio)  →  Qwen3-VL (via OpenRouter)
Do NOT reorder without updating docs/architecture.md.

The pipeline renders a chart to PNG server-side (Plotly, headless) and sends the
image to the VLM; the same groundedness discipline as text narration applies.
"""

from __future__ import annotations

from typing import ClassVar


class VLMService:
    PROVIDER_ORDER: ClassVar[tuple[str, ...]] = ("gemini_flash", "qwen3_vl_openrouter")

    async def interpret(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "VLM chart interpretation lands in Phase 3 (feature 2.1). "
            "Provider order is fixed here: " + " -> ".join(self.PROVIDER_ORDER)
        )
