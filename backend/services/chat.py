"""Chat orchestration — runs the agent, verifies its answer, caches it.

**What changed and why.** This used to retrieve chunks from pgvector and hand them
to a model. It now runs `services/agent.py`, which queries the database directly
through two tools. Retrieval was removed rather than tuned because the failures it
produced were not tuning problems: a superlative is a claim about every country and
retrieval is definitionally a subset, and a question about Japan returns Estonia
because those two sentences are near-identical in embedding space. See decision
#38.

**What deliberately did not change.** The SSE contract is the same —
`citations`, `token`*, exactly one `verdict`, then `done` — so the chat UI needed
no rewrite, and decision #27's arrangement survives: text is provisional until the
verdict promotes or retracts it. One event type is added, `tool`, because an agent
spends its first seconds calling tools rather than emitting prose and a blank panel
during that is worse than a visible "querying…".

**The one honest downgrade.** The final answer is no longer streamed token by
token. A tool-calling turn is not a token stream — the model's first output is a
structured call — and threading a second, streamed request through three provider
dialects to recover the typing effect would add a code path whose only job is
cosmetic. The answer is emitted as one `token` event, still provisional, still
verified before the verdict. Time to *first feedback* is better than it was,
because tool events start arriving within a second; time to first prose is worse.

Verification is unchanged in substance and stronger in fact: `verify()` runs
against the tool payloads, which are exactly the numbers the model was shown.
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
from services.agent import AgentAnswer, evidence_context, run_agent
from services.agent_tools import ToolResult
from services.cache import (
    TASK_RAG_ANSWER,
    build_cache_key,
    get_cached_response,
    store_response,
)
from services.groundedness import verify
from services.telemetry import ChatTrace

logger = get_logger(__name__)

#: What to try instead. Kept separate from the sentence announcing the gap, because
#: the tools often supply a far better one of those than this module could.
SUGGESTION = (
    "EconRadar holds official macroeconomic series from the World Bank, IMF, FRED, "
    "BIS and the World Bank DataBank — try naming a country and an indicator such as "
    "inflation, GDP growth, unemployment or government debt."
)

INSUFFICIENT_DATA = f"The data available here does not cover that. {SUGGESTION}"


@dataclass(frozen=True, slots=True)
class Citation:
    index: int
    country_code: str | None
    country_name: str | None
    indicator_code: str | None
    indicator_name: str | None
    chunk_type: str | None
    similarity: float


def citations_for(results: list[ToolResult]) -> list[Citation]:
    """Citation cards, one per (country, indicator) the tools actually returned.

    The shape is unchanged from the retrieval era so the existing cards keep
    working, but `similarity` is now always 1.0 and means something different: it
    was a cosine distance to a chunk, and it is now the fact that this row *is* the
    record rather than the nearest thing to it. Kept in the payload rather than
    removed, because dropping a field would break the client for no gain.
    """
    seen: dict[tuple[str | None, str | None], Citation] = {}
    for result in results:
        if not result.ok:
            continue
        indicator = result.payload.get("indicator") or {}
        for country_code, indicator_code in result.references:
            key = (country_code, indicator_code)
            if key in seen:
                continue
            seen[key] = Citation(
                index=len(seen) + 1,
                country_code=country_code,
                country_name=_country_name(result, country_code),
                indicator_code=indicator_code,
                indicator_name=indicator.get("indicator_name"),
                chunk_type=result.name,
                similarity=1.0,
            )
    return list(seen.values())


def _country_name(result: ToolResult, code: str | None) -> str | None:
    if result.payload.get("country_code") == code:
        return result.payload.get("country_name")
    for row in result.payload.get("rankings", []):
        if row.get("country_code") == code:
            return row.get("country_name")
    return None


_CITATION_RE = re.compile(r"\[(\d{1,2})\]")


def split_citation_markers(text: str) -> tuple[str, list[int]]:
    """Separate the prose from the `[n]` markers, returning both.

    A citation marker is structural markup, not a numeric claim, but `[4]` matches
    the verifier's number pattern exactly as a bare `4` would. Verifying the raw
    answer made groundedness depend on whether a citation index happened to coincide
    with some figure in the evidence — `[6]` passed only because `round(5.8, 0) == 6`,
    and `[4]` failed the same answer for no better reason (decision #30).

    Stripping them removes that coincidence. The indices are not discarded: they are
    checked against the evidence list instead, which is a real test the number
    pattern was never performing.
    """
    return _CITATION_RE.sub("", text), [int(m.group(1)) for m in _CITATION_RE.finditer(text)]


def _cache_key(question: str, results: list[ToolResult]) -> str:
    """Keyed by the question *and* the evidence that answered it.

    The same question asked after an ingestion run reads different rows and must not
    share an answer, so the tool payloads are part of the key rather than the
    question alone. Content-addressed, exactly like every other cache key here
    (decision #31): a matching key means identical inputs.
    """
    fingerprint = hashlib.sha256(
        "|".join(f"{r.name}:{r.payload}" for r in results).encode("utf-8")
    ).hexdigest()[:16]
    return build_cache_key(
        TASK_RAG_ANSWER,
        question=" ".join(question.lower().split()),
        evidence=fingerprint,
    )


async def stream_chat(
    session: AsyncSession,
    question: str,
    history: list[dict[str, str]] | None = None,
    **_ignored: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE-shaped events for one question."""
    question = (question or "").strip()
    if not question:
        yield {"type": "error", "message": "Ask a question about the data."}
        yield {"type": "done"}
        return

    if not settings.agent_enabled or not settings.llm_enabled:
        yield {"type": "error", "message": "AI answering is disabled on this deployment."}
        yield {"type": "done"}
        return

    # Assembled as the request happens and emitted exactly once, at whichever exit
    # is taken — there are six, and an early return that skipped the line would make
    # the counters describe only the happy path (decision #45).
    trace = ChatTrace(question_chars=len(question))

    answer: AgentAnswer | None = None
    results: list[ToolResult] = []
    async for kind, item in run_agent(session, question, history or []):
        if kind == "tool":
            results.append(item)
            yield {"type": "tool", "name": item.name, "summary": item.summary(), "ok": item.ok}
        else:
            answer = item

    trace.tools = [r.name for r in results]
    trace.tool_failures = sum(1 for r in results if not r.ok)
    if answer is not None:
        trace.provider, trace.model = answer.provider, answer.model
        trace.fallbacks = list(answer.attempts)
        trace.rows, trace.ranked = answer.rows_read, answer.called_ranking
        trace.countries_ranked = answer.countries_ranked
        trace.seconds, trace.timed_out = answer.seconds, answer.timed_out

    citations = citations_for(results)
    yield {"type": "citations", "citations": [asdict(c) for c in citations]}

    if results and not any(r.ok for r in results):
        # Every lookup came back empty. The model is not asked to write about that,
        # because a model asked to explain an absence writes around it — the first
        # live run on a country the database does not hold produced prose the
        # verifier then had to retract, which is a correct outcome presented as a
        # failure. This message is assembled from the tool errors themselves, so it
        # cannot contain a figure, and the reader is told plainly rather than shown
        # a retraction.
        detail = " ".join(
            dict.fromkeys(r.reader_message for r in results if r.reader_message)
        ).strip()
        logger.info("chat: every tool call came back empty — %s", detail[:200])
        # The generic blurb only when there is nothing specific to say. Appending it
        # to a precise message ("EconRadar holds no inflation for Gibraltar — the
        # series covers 193 other countries") restates the same fact twice and reads
        # like the system did not hear itself.
        yield {"type": "token", "text": f"{detail} {SUGGESTION}".strip() or INSUFFICIENT_DATA}
        yield {
            "type": "verdict",
            "grounded": True,
            "score": 1.0,
            "provider": "none",
            "model": "data-absent",
            "cached": False,
        }
        # Counted apart from a retraction on purpose. Both withhold a figure, and
        # only one of them means something went wrong.
        trace.outcome, trace.grounded = "absent", True
        trace.emit()
        yield {"type": "done"}
        return

    if answer is None or answer.failure or not answer.text:
        # Every one of these is a real outcome with a reason, and the reason is
        # reported rather than smoothed into a generic apology.
        reason = (answer.failure if answer else None) or "the agent produced no answer"
        logger.warning("chat produced no answer: %s", reason)
        yield {"type": "token", "text": INSUFFICIENT_DATA if not results else ""}
        yield {
            "type": "verdict",
            "grounded": False,
            "score": 0.0,
            "provider": answer.provider if answer else None,
            "model": None,
            "cached": False,
            "reason": reason,
        }
        trace.outcome = "timeout" if (answer and answer.timed_out) else "refused"
        trace.reason = reason
        trace.emit()
        yield {"type": "done"}
        return

    context = evidence_context(results)
    key = _cache_key(question, results)
    hit = await get_cached_response(session, key)
    if hit is not None:
        # Cached *after* the tools ran, because the key is the evidence: the tool
        # calls are cheap local queries, the model turn is the expensive part, and
        # skipping the queries would mean not knowing whether the cached answer still
        # matches the data.
        yield {"type": "token", "text": hit.text}
        yield {
            "type": "verdict",
            "grounded": True,
            "score": hit.groundedness_score,
            "provider": hit.provider,
            "model": hit.model,
            "cached": True,
        }
        trace.outcome, trace.grounded, trace.cached = "answered", True, True
        trace.groundedness = hit.groundedness_score
        trace.provider, trace.model = hit.provider, hit.model
        trace.emit()
        yield {"type": "done"}
        return

    yield {"type": "token", "text": answer.text}

    prose, cited = split_citation_markers(answer.text)
    report = verify(prose, context)
    dangling = sorted({i for i in cited if not 1 <= i <= len(citations)})
    if not report.passed or dangling:
        # Retraction, not repair. The client discards what it rendered and nothing is
        # cached, so the fabrication cannot be served again.
        reason = (
            report.reason()
            if not report.passed
            else "citation markers with no evidence behind them: "
            + ", ".join(f"[{i}]" for i in dangling)
        )
        logger.warning(
            "chat answer failed verification (score=%.2f, %s) — retracting", report.score, reason
        )
        yield {
            "type": "verdict",
            "grounded": False,
            "score": report.score,
            "provider": answer.provider,
            "model": answer.model,
            "cached": False,
            "reason": reason,
        }
        trace.outcome, trace.reason = "retracted", reason
        trace.groundedness = report.score
        trace.emit()
        yield {"type": "done"}
        return

    await store_response(
        session,
        cache_key=key,
        task_type=TASK_RAG_ANSWER,
        response_text=answer.text,
        provider=answer.provider,
        model=answer.model,
        groundedness_score=report.score,
    )
    trace.outcome, trace.grounded = "answered", True
    trace.groundedness = report.score
    trace.derived_figures = len(report.extra.get("derived", []))
    trace.emit()
    yield {
        "type": "verdict",
        "grounded": True,
        "score": report.score,
        "provider": answer.provider,
        "model": answer.model,
        "cached": False,
    }
    yield {"type": "done"}


async def answer_chat(
    session: AsyncSession,
    question: str,
    history: list[dict[str, str]] | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Non-streaming form — the same pipeline, collected. Used by tests and clients
    that cannot consume SSE."""
    text_parts: list[str] = []
    citations: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    verdict: dict[str, Any] | None = None
    error: str | None = None

    async for event in stream_chat(session, question, history):
        if event["type"] == "token":
            text_parts.append(event["text"])
        elif event["type"] == "citations":
            citations = event["citations"]
        elif event["type"] == "tool":
            tools.append(event)
        elif event["type"] == "verdict":
            verdict = event
        elif event["type"] == "error":
            error = event["message"]

    grounded = bool(verdict and verdict.get("grounded"))
    return {
        "answer": "".join(text_parts).strip() if grounded else "",
        "citations": citations,
        "tools": tools,
        "grounded": grounded,
        "groundedness_score": (verdict or {}).get("score"),
        "provider": (verdict or {}).get("provider"),
        "cached": bool((verdict or {}).get("cached")),
        "error": error
        or (verdict or {}).get("reason")
        or (None if grounded else "The answer could not be verified against the data."),
    }


def rag_available() -> bool:
    """Kept under its old name: `/status` and the health payload both call it."""
    from services.agent import agent_available

    return agent_available()
