"""Hybrid retrieval and grounded answering (feature 2.2).

**Hybrid** means the vector search is narrowed by metadata the question itself
names. Asked about Nigeria, pure cosine similarity will happily return Ghana and
Kenya — the sentences are nearly identical in shape, and their embeddings sit on
top of each other. Detecting "Nigeria" in the question and filtering on
`country_code` is what turns a plausible answer into a correct one.

The filter is applied as a *preference*, not a hard restriction: filtered results
come first, and the unfiltered search backfills the remaining slots. A question
mentioning one country but asking a comparative question ("how does Nigeria
compare?") still needs the others, and features.md 2.2 explicitly warns against
retrieval silently truncating a question that spans many countries.

**Nothing relevant retrieved means the answer is a refusal.** That is the
acceptance criterion and it is enforced before a model is called at all: below
the similarity floor there is no prompt, no generation, and no opportunity to
answer from parametric memory.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from logging_config import get_logger
from models import CountryProfile, Embedding, IndicatorCatalog
from services.embeddings import EmbeddingUnavailable, embed_query

logger = get_logger(__name__)

INSUFFICIENT_DATA = (
    "The data available here does not cover that. EconRadar holds official "
    "macroeconomic series from the World Bank, IMF, FRED, BIS and the World Bank "
    "DataBank — try naming a country and an indicator such as inflation, GDP growth, "
    "unemployment or government debt."
)

# Short, ambiguous country names that would match half the questions asked.
_NAME_STOPWORDS = {"chad", "jordan", "georgia", "guinea", "niger", "turkey", "mali"}

#: Slots held back from the metadata filter for the unfiltered search, so a
#: comparative question always retrieves something outside the country it named.
_OPEN_SLOTS = 3


@dataclass(frozen=True, slots=True)
class Evidence:
    chunk_text: str
    chunk_type: str | None
    country_code: str | None
    country_name: str | None
    indicator_code: str | None
    indicator_name: str | None
    similarity: float


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    evidence: list[Evidence]
    countries: list[str]
    indicators: list[str]

    @property
    def is_empty(self) -> bool:
        return not self.evidence


def _names_country(name: str, lowered: str, words: set[str]) -> bool:
    """Whether a question mentions this country.

    Two forms, both of which a naive substring check gets wrong. A word boundary
    rather than space padding, because "…compare with Ghana?" ends in punctuation
    and " ghana " never matches it. And an adjectival prefix, because "Brazilian
    policy rates" is a question about Brazil and " brazil " is not in it.
    """
    if re.search(rf"\b{re.escape(name)}\b", lowered):
        return True
    # "brazilian" -> "brazil", "ghanaian" -> "ghana". Bounded so a long unrelated
    # word cannot match a short country name by sharing its opening letters.
    return len(name) >= 5 and any(
        word.startswith(name) and len(word) <= len(name) + 4 for word in words
    )


async def detect_filters(session: AsyncSession, question: str) -> tuple[list[str], list[uuid.UUID]]:
    """Country codes and indicator ids the question names.

    Matched against the database's own country names and indicator names rather
    than a hand-written keyword list, so the filter stays correct as coverage
    changes. Short ambiguous names are excluded — "Chad" and "Jordan" appear in
    English sentences that have nothing to do with either country.
    """
    lowered = f" {question.lower()} "
    words = set(re.findall(r"[a-z]{2,}", lowered))

    countries: list[str] = []
    for code, name in (
        (await session.execute(select(CountryProfile.country_code, CountryProfile.country_name)))
        .tuples()
        .all()
    ):
        lower_name = name.lower()
        if lower_name in _NAME_STOPWORDS:
            if re.search(rf"\b{re.escape(lower_name)}\b", lowered) and (
                "gdp" in lowered or "inflation" in lowered or "economy" in lowered
            ):
                countries.append(code)
            continue
        if _names_country(lower_name, lowered, words) or code.lower() in words:
            countries.append(code)

    indicators: list[uuid.UUID] = []
    for ind_id, ind_name, ind_code in (
        (
            await session.execute(
                select(
                    IndicatorCatalog.id,
                    IndicatorCatalog.indicator_name,
                    IndicatorCatalog.indicator_code,
                )
            )
        )
        .tuples()
        .all()
    ):
        # The catalog name is a full label ("Inflation, consumer prices (annual %)"),
        # so match on its leading concept word rather than the whole string.
        concept = re.split(r"[,(]", ind_name or "")[0].strip().lower()
        if (concept and len(concept) > 3 and concept in lowered) or ind_code.lower() in lowered:
            indicators.append(ind_id)

    return countries, indicators


async def _search(
    session: AsyncSession,
    vector: list[float],
    *,
    limit: int,
    countries: list[str] | None = None,
    indicators: list[uuid.UUID] | None = None,
    exclude_keys: set[str] | None = None,
) -> tuple[list[Evidence], list[str]]:
    distance = Embedding.embedding.cosine_distance(vector)
    stmt = (
        select(
            Embedding.chunk_key,
            Embedding.chunk_text,
            Embedding.chunk_type,
            Embedding.country_code,
            CountryProfile.country_name,
            IndicatorCatalog.indicator_code,
            IndicatorCatalog.indicator_name,
            distance.label("distance"),
        )
        .outerjoin(CountryProfile, CountryProfile.country_code == Embedding.country_code)
        .outerjoin(IndicatorCatalog, IndicatorCatalog.id == Embedding.indicator_id)
        .order_by(distance)
        .limit(limit)
    )
    if countries:
        stmt = stmt.where(Embedding.country_code.in_(countries))
    if indicators:
        # Indicator-level chunks OR the country-level chunk, which carries no
        # indicator but is often what a coverage question actually needs.
        stmt = stmt.where(
            or_(Embedding.indicator_id.in_(indicators), Embedding.indicator_id.is_(None))
        )
    if exclude_keys:
        stmt = stmt.where(Embedding.chunk_key.not_in(exclude_keys))

    rows = (await session.execute(stmt)).all()
    return [
        Evidence(
            chunk_text=r.chunk_text,
            chunk_type=r.chunk_type,
            country_code=r.country_code,
            country_name=r.country_name,
            indicator_code=r.indicator_code,
            indicator_name=r.indicator_name,
            # pgvector returns cosine *distance*; similarity is what the threshold
            # is expressed in, and what a reader would expect to see.
            similarity=1.0 - float(r.distance),
        )
        for r in rows
    ], [r.chunk_key for r in rows]


async def retrieve(session: AsyncSession, question: str) -> RetrievalResult:
    """Hybrid retrieval: metadata-narrowed vector search, backfilled by open search."""
    if not question.strip():
        return RetrievalResult([], [], [])

    try:
        vector = await embed_query(question)
    except EmbeddingUnavailable as exc:
        logger.error("retrieval failed — embeddings unavailable: %s", exc)
        return RetrievalResult([], [], [])

    countries, indicators = await detect_filters(session, question)
    top_k = settings.rag_top_k

    evidence: list[Evidence] = []
    seen: set[str] = set()
    if countries or indicators:
        # Slots are *reserved* for the open search rather than merely left over.
        # Letting the filter take all of them is how "compare Nigeria with Ghana"
        # comes back as eight Nigerian chunks and no Ghanaian one — the failure
        # features.md 2.2 describes as retrieval silently truncating the question.
        filtered, keys = await _search(
            session,
            vector,
            limit=max(1, top_k - _OPEN_SLOTS),
            countries=countries or None,
            indicators=indicators or None,
        )
        evidence.extend(filtered)
        seen.update(keys)

    if len(evidence) < top_k:
        extra, _ = await _search(
            session, vector, limit=top_k - len(evidence), exclude_keys=seen or None
        )
        evidence.extend(extra)

    relevant = [e for e in evidence if e.similarity >= settings.rag_min_similarity]
    relevant.sort(key=lambda e: e.similarity, reverse=True)

    logger.info(
        "retrieval: q=%r countries=%s indicators=%d retrieved=%d relevant=%d best=%.3f",
        question[:80],
        countries,
        len(indicators),
        len(evidence),
        len(relevant),
        max((e.similarity for e in evidence), default=0.0),
    )
    return RetrievalResult(
        evidence=relevant,
        countries=countries,
        indicators=[str(i) for i in indicators],
    )


def evidence_context(result: RetrievalResult) -> dict[str, Any]:
    """The object the answer is verified against — the retrieved text and nothing else."""
    return {
        "evidence": [
            {
                "chunk_text": e.chunk_text,
                "country_code": e.country_code,
                "indicator_code": e.indicator_code,
            }
            for e in result.evidence
        ]
    }


def trim_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep the last N turns (feature 2.2 specifies four).

    Counted in turns rather than messages, and the trim is from the end, so a long
    conversation keeps its most recent context rather than its opening.
    """
    clean = [
        {"role": t.get("role", "user"), "content": (t.get("content") or "").strip()}
        for t in history
        if (t.get("content") or "").strip()
    ]
    return clean[-(settings.rag_context_turns * 2) :]


async def corpus_size(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(Embedding))).scalar_one()
