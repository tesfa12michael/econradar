"""Chat orchestration for the RAG Q&A (feature 2.2) — retrieve, stream, verify, cache.

**Streaming and verification are in tension, and the resolution is deliberate.**
The design system wants a response beginning within about a second, which means
tokens go out before the answer is complete. Decision #8 wants no fabricated
number ever presented as fact. Both cannot be fully satisfied by streaming alone,
and a fabricated figure can straddle two deltas, so a per-chunk check would not
catch it either.

So the stream is explicitly provisional. Tokens are emitted as they arrive and the
client renders them in a "verifying" state; when generation finishes, the
reassembled answer is checked against the retrieved evidence and a terminal
`verdict` event says whether it stands. A failed verdict retracts the text in the
UI and is never written to the cache. The verification is visible rather than
hidden, which is the honest arrangement — and the retraction path is exercised by
a test rather than assumed.

Retrieval happens before any model is called, so a question with no relevant
evidence is refused without a generation step at all.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from logging_config import get_logger
from services import prompts
from services.cache import (
    TASK_RAG_ANSWER,
    build_cache_key,
    get_cached_response,
    store_response,
)
from services.groundedness import verify
from services.llm import LLMService
from services.providers import ProviderError, ProviderNotConfigured, ProviderRateLimited
from services.rag import (
    INSUFFICIENT_DATA,
    Evidence,
    RetrievalResult,
    evidence_context,
    retrieve,
    trim_history,
)

logger = get_logger(__name__)

MAX_WORDS = 220


@dataclass(frozen=True, slots=True)
class Citation:
    index: int
    country_code: str | None
    country_name: str | None
    indicator_code: str | None
    indicator_name: str | None
    chunk_type: str | None
    similarity: float


def citations_for(result: RetrievalResult) -> list[Citation]:
    """Citation cards, numbered to match the [n] markers the prompt asks for."""
    return [
        Citation(
            index=i,
            country_code=e.country_code,
            country_name=e.country_name,
            indicator_code=e.indicator_code,
            indicator_name=e.indicator_name,
            chunk_type=e.chunk_type,
            similarity=round(e.similarity, 3),
        )
        for i, e in enumerate(result.evidence, start=1)
    ]


_CITATION_RE = re.compile(r"\[(\d{1,2})\]")


def split_citation_markers(text: str) -> tuple[str, list[int]]:
    """Separate the prose from the `[n]` markers, returning both.

    A citation marker is structural markup, not a numeric claim, but `[4]` matches
    the verifier's number pattern exactly as a bare `4` would. Verifying the raw
    answer therefore made groundedness depend on whether a citation index happened
    to coincide with some figure in the evidence — `[6]` passed only because
    `round(5.8, 0) == 6`, and `[4]` failed the same answer for no better reason.

    Stripping them removes that coincidence. The indices are not discarded, though:
    they are checked against the evidence list instead, which is a real test the
    number pattern was never performing — a marker pointing past the end of the
    evidence is a fabricated citation.
    """
    return _CITATION_RE.sub("", text), [int(m.group(1)) for m in _CITATION_RE.finditer(text)]


def _cache_key(question: str, evidence: list[Evidence]) -> str:
    """Keyed by the question *and* the evidence that answered it.

    Two identical questions asked after an ingestion run retrieve different
    evidence and must not share an answer, so the retrieved chunks are part of the
    key rather than the question alone.
    """
    fingerprint = hashlib.sha256(
        "|".join(e.chunk_text for e in evidence).encode("utf-8")
    ).hexdigest()[:16]
    return build_cache_key(
        TASK_RAG_ANSWER,
        question=" ".join(question.lower().split()),
        evidence=fingerprint,
    )


def _messages(question: str, result: RetrievalResult, history: list[dict[str, str]]):
    user_prompt = prompts.render(
        "rag_answer.j2",
        max_words=MAX_WORDS,
        question=question,
        evidence=[{"chunk_text": e.chunk_text} for e in result.evidence],
        history=history,
    )
    return prompts.chat_messages(user_prompt)


async def stream_chat(
    session: AsyncSession,
    question: str,
    history: list[dict[str, str]] | None = None,
    *,
    service: LLMService | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE-shaped events for one question."""
    question = (question or "").strip()
    if not question:
        yield {"type": "error", "message": "Ask a question about the data."}
        yield {"type": "done"}
        return

    turns = trim_history(history or [])
    result = await retrieve(session, question)
    yield {"type": "citations", "citations": [asdict(c) for c in citations_for(result)]}

    if result.is_empty:
        # The acceptance criterion: an insufficient-data fallback instead of a
        # fabricated answer. No model is called, so none can be tempted.
        logger.info("chat refused (no relevant evidence): %r", question[:80])
        yield {"type": "token", "text": INSUFFICIENT_DATA}
        yield {
            "type": "verdict",
            "grounded": True,
            "score": 1.0,
            "provider": "none",
            "model": "retrieval-refusal",
            "cached": False,
        }
        yield {"type": "done"}
        return

    key = _cache_key(question, result.evidence)
    hit = await get_cached_response(session, key)
    if hit is not None:
        yield {"type": "token", "text": hit.text}
        yield {
            "type": "verdict",
            "grounded": True,
            "score": hit.groundedness_score,
            "provider": hit.provider,
            "model": hit.model,
            "cached": True,
        }
        yield {"type": "done"}
        return

    if not settings.llm_enabled:
        yield {"type": "error", "message": "AI answering is disabled on this deployment."}
        yield {"type": "done"}
        return

    llm = service or LLMService()
    context = evidence_context(result)
    messages = _messages(question, result, turns)

    # Groq first — the speed layer (decision #24's routing), then the rest of the
    # rotation. Streaming is attempted per provider; a provider that fails
    # mid-stream hands over like any other failure.
    chunks: list[str] = []
    used_provider: str | None = None
    attempts: list[str] = []
    for provider in llm.available(primary="groq"):
        chunks = []
        try:
            async for delta in llm.stream_answer(messages, provider=provider):
                chunks.append(delta)
                yield {"type": "token", "text": delta}
        except (ProviderRateLimited, ProviderNotConfigured, ProviderError) as exc:
            attempts.append(f"{provider}: {exc}")
            logger.warning("chat stream: %s failed, falling back — %s", provider, exc)
            if chunks:
                # Partial text already reached the client; tell it to start over
                # rather than concatenating two providers' half-answers.
                yield {"type": "reset"}
            continue

        if chunks:
            used_provider = provider
            break
        attempts.append(f"{provider}: empty stream")

    answer = "".join(chunks).strip()
    if not answer or used_provider is None:
        logger.warning("chat produced no answer: %s", "; ".join(attempts))
        yield {"type": "error", "message": "No provider was able to answer. Please try again."}
        yield {"type": "done"}
        return

    prose, cited = split_citation_markers(answer)
    report = verify(prose, context)
    dangling = sorted({i for i in cited if not 1 <= i <= len(result.evidence)})
    if not report.passed or dangling:
        # Retraction, not repair. The client discards what it rendered and nothing
        # is cached, so the fabrication cannot be served again.
        reason = (
            report.reason()
            if not report.passed
            else "citation markers with no evidence behind them: "
            + ", ".join(f"[{i}]" for i in dangling)
        )
        logger.warning(
            "chat answer failed verification (score=%.2f, %s) — retracting",
            report.score,
            reason,
        )
        yield {
            "type": "verdict",
            "grounded": False,
            "score": report.score,
            "provider": used_provider,
            "model": None,
            "cached": False,
            "reason": reason,
        }
        yield {"type": "done"}
        return

    await store_response(
        session,
        cache_key=key,
        task_type=TASK_RAG_ANSWER,
        response_text=answer,
        provider=used_provider,
        model=None,
        groundedness_score=report.score,
    )
    logger.info(
        "chat answered: provider=%s evidence=%d groundedness=%.2f",
        used_provider,
        len(result.evidence),
        report.score,
    )
    yield {
        "type": "verdict",
        "grounded": True,
        "score": report.score,
        "provider": used_provider,
        "model": None,
        "cached": False,
    }
    yield {"type": "done"}


async def answer_chat(
    session: AsyncSession,
    question: str,
    history: list[dict[str, str]] | None = None,
    *,
    service: LLMService | None = None,
) -> dict[str, Any]:
    """Non-streaming form — the same pipeline, collected. Used by tests and clients
    that cannot consume SSE."""
    text_parts: list[str] = []
    citations: list[dict[str, Any]] = []
    verdict: dict[str, Any] | None = None
    error: str | None = None

    async for event in stream_chat(session, question, history, service=service):
        if event["type"] == "token":
            text_parts.append(event["text"])
        elif event["type"] == "reset":
            text_parts.clear()
        elif event["type"] == "citations":
            citations = event["citations"]
        elif event["type"] == "verdict":
            verdict = event
        elif event["type"] == "error":
            error = event["message"]

    grounded = bool(verdict and verdict.get("grounded"))
    return {
        "answer": "".join(text_parts).strip() if grounded else "",
        "citations": citations,
        "grounded": grounded,
        "groundedness_score": (verdict or {}).get("score"),
        "provider": (verdict or {}).get("provider"),
        "cached": bool((verdict or {}).get("cached")),
        "error": error
        or (None if grounded else "The answer could not be verified against the data."),
    }


def rag_available() -> bool:
    return settings.llm_enabled and bool(LLMService().available())
