"""Intelligence-layer API — forecasting, VLM interpretation, RAG Q&A.

Grouped away from `data.py` because these routes share a property the data routes
do not: **every one of them can legitimately have nothing to return.** A model may
be unreachable, a series too short, a provider rate-limited, retrieval empty. Each
of those is a 404 with a reason, never a fabricated body — which is the API-layer
expression of decision #8.

They also share a latency profile. The design system forbids AI content blocking
page load, so the frontend calls these from separate, non-blocking panels while the
historical chart renders from `data.py` immediately.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session
from schemas import (
    AnomalyExplanationOut,
    ChartInterpretationOut,
    ChatRequest,
    ChatResponse,
    ForecastOut,
    ForecastPointOut,
)
from services import ratelimit
from services.anomaly_explain import explain_anomalies
from services.chat import answer_chat, stream_chat
from services.forecast_store import get_forecast
from services.vlm_interpret import interpret_chart

router = APIRouter(tags=["ai"])


def _iso3(country_code: str) -> str:
    code = country_code.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise HTTPException(
            status_code=422, detail=f"country_code must be ISO-3 alpha, got {country_code!r}"
        )
    return code


def _history(request: ChatRequest) -> list[dict[str, str]]:
    """Conversation turns as plain dicts. Trimming to the documented four turns
    happens in `services/agent.py`, so the limit is enforced once, server-side,
    however the request arrived."""
    return [turn.model_dump() for turn in request.history]


def rate_limited(http: Request) -> None:
    """Reject a caller over any chat limit (decision #43).

    A dependency rather than middleware, so it guards exactly the two routes that
    spend model quota and nothing else — the map and country pages are free to
    serve, and rate-limiting them would be all cost and no protection.

    `Retry-After` is real, not a constant: a caller told to come back in a second
    when the answer is "tomorrow" will simply retry in a second.
    """
    decision = ratelimit.limiter().check(
        ratelimit.client_key(dict(http.headers), http.client.host if http.client else None)
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail=decision.detail,
            headers={"Retry-After": str(decision.retry_after)},
        )


@router.get("/forecast/{country_code}", response_model=ForecastOut)
async def get_series_forecast(
    country_code: str,
    indicator: str = Query(description="Indicator code to forecast"),
    session: AsyncSession = Depends(get_session),
) -> ForecastOut:
    """Quantile forecast for one series (feature 1.4).

    Served from `forecast_cache` when warm. A miss walks the Chronos-2 -> TimesFM ->
    StatsForecast cascade and stores the result, so the Modal round trip is paid at
    most once per version of a series.
    """
    iso3 = _iso3(country_code)
    forecast = await get_forecast(session, iso3, indicator.strip())
    if forecast is None:
        raise HTTPException(
            status_code=404,
            detail=f"No forecast available for {iso3} / {indicator!r}. The series may "
            "be absent, too short to forecast, or every model in the cascade may have failed.",
        )
    return ForecastOut(
        country_code=forecast.country_code,
        indicator_code=forecast.indicator_code,
        indicator_name=forecast.indicator_name,
        unit=forecast.unit,
        frequency=forecast.frequency,
        model_used=forecast.model_used,
        horizon=forecast.horizon,
        points=[
            ForecastPointOut(date=p.date, median=p.median, lower=p.lower, upper=p.upper)
            for p in forecast.points
        ],
        cached=forecast.cached,
        generated_at=forecast.generated_at,
    )


@router.get("/vlm-interpret/{country_code}", response_model=ChartInterpretationOut)
async def get_chart_interpretation(
    country_code: str,
    indicator: str = Query(description="Indicator code whose chart to interpret"),
    session: AsyncSession = Depends(get_session),
) -> ChartInterpretationOut:
    """A vision model's reading of this series' chart (feature 2.1).

    The chart is rendered here, server-side, from the same data the page plots — so
    the description is of the image the reader is looking at, not of one the model
    imagined. Cached for seven days.
    """
    iso3 = _iso3(country_code)
    interpretation = await interpret_chart(session, iso3, indicator.strip())
    if interpretation is None:
        raise HTTPException(
            status_code=404,
            detail=f"No chart interpretation available for {iso3} / {indicator!r}. The "
            "series may be absent, the chart may have failed to render, or no vision "
            "provider returned a grounded reading.",
        )
    return ChartInterpretationOut(
        country_code=interpretation.country_code,
        indicator_code=interpretation.indicator_code,
        text=interpretation.text,
        provider=interpretation.provider,
        model=interpretation.model,
        groundedness_score=interpretation.groundedness_score,
        cached=interpretation.cached,
    )


@router.get("/anomaly-explanations/{country_code}", response_model=list[AnomalyExplanationOut])
async def get_anomaly_explanations(
    country_code: str,
    indicator: str = Query(description="Indicator code whose anomalies to explain"),
    limit: int = Query(default=3, ge=1, le=10),
    session: AsyncSession = Depends(get_session),
) -> list[AnomalyExplanationOut]:
    """Grounded explanations for this series' most notable anomalies (feature 2.3).

    Generated on first view and written to `anomalies.llm_explanation`, where they
    persist — anomaly retraction is timestamp-based specifically so a re-score does
    not discard them.
    """
    iso3 = _iso3(country_code)
    explanations = await explain_anomalies(session, iso3, indicator.strip(), limit=limit)
    return [
        AnomalyExplanationOut(
            country_code=e.country_code,
            indicator_code=e.indicator_code,
            date=e.date,
            value=e.value,
            z_score=e.z_score,
            deviation_type=e.deviation_type,
            explanation=e.explanation,
            cached=e.cached,
        )
        for e in explanations
    ]


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(rate_limited)])
async def post_chat(
    request: ChatRequest, session: AsyncSession = Depends(get_session)
) -> ChatResponse:
    """Grounded, cited answer to one question (feature 2.2), collected.

    The streaming form is `/chat/stream`; this one is for callers that cannot
    consume SSE, and it returns only answers that passed verification.
    """
    result = await answer_chat(session, request.question, _history(request))
    return ChatResponse(**result)


@router.post("/chat/stream", dependencies=[Depends(rate_limited)])
async def post_chat_stream(
    request: ChatRequest, session: AsyncSession = Depends(get_session)
) -> StreamingResponse:
    """Server-sent events for the chat UI (feature 2.2).

    Event order is `citations`, then `token`* (possibly interrupted by `reset` if
    a provider fails mid-stream), then exactly one `verdict`, then `done`. The
    tokens are **provisional**: the client must not present them as a final answer
    until the verdict arrives, because groundedness can only be checked on the
    reassembled text. A `grounded: false` verdict means retract what was rendered.
    """

    async def events() -> AsyncIterator[str]:
        async for event in stream_chat(session, request.question, _history(request)):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Tells any intermediate proxy not to buffer, which would collect the
            # whole stream and defeat the point of streaming it.
            "X-Accel-Buffering": "no",
        },
    )
