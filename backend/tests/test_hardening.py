"""Abuse limits and agent telemetry (decisions #43 and #45).

`POST /api/v1/chat` is public, unauthenticated, and spends two to three model turns
of free-tier quota on every cache miss. Nothing here is about correctness of
answers; it is about what one client can cost before somebody notices.

The tests are written against the *ceilings*, not against particular numbers, so
tuning a limit in `config.py` does not turn into a red suite.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from config import settings
from services import ratelimit, telemetry
from services.ratelimit import ChatRateLimiter, client_key
from services.telemetry import ChatCounters, ChatTrace


@pytest.fixture
def limiter(monkeypatch: pytest.MonkeyPatch) -> ChatRateLimiter:
    monkeypatch.setattr(settings, "chat_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "chat_rate_limit_per_minute", 3)
    monkeypatch.setattr(settings, "chat_rate_limit_per_day", 5)
    monkeypatch.setattr(settings, "chat_global_limit_per_day", 8)
    return ChatRateLimiter()


# ── the burst window ─────────────────────────────────────────────────────────


def test_a_client_is_stopped_at_the_burst_limit(limiter: ChatRateLimiter) -> None:
    for i in range(3):
        assert limiter.check("1.2.3.4", now=100.0 + i).allowed, f"request {i} should pass"
    blocked = limiter.check("1.2.3.4", now=103.0)
    assert not blocked.allowed
    assert blocked.scope == "client_minute"
    assert 0 < blocked.retry_after <= 61


def test_a_refusal_does_not_consume_allowance(limiter: ChatRateLimiter) -> None:
    """The subtle way a limiter breaks: if rejections count, a client held at the
    limit keeps their own window full and never recovers."""
    for i in range(3):
        limiter.check("1.2.3.4", now=100.0 + i)
    for i in range(20):  # hammered while blocked
        assert not limiter.check("1.2.3.4", now=110.0 + i).allowed

    # The first window has now rolled off; the client is served again.
    assert limiter.check("1.2.3.4", now=161.0).allowed


def test_clients_are_limited_separately(limiter: ChatRateLimiter) -> None:
    for i in range(3):
        limiter.check("1.2.3.4", now=100.0 + i)
    assert limiter.check("5.6.7.8", now=103.0).allowed


# ── the daily ceilings ───────────────────────────────────────────────────────


def test_a_patient_client_is_stopped_by_the_daily_cap(limiter: ChatRateLimiter) -> None:
    """A burst limit alone permits six a minute forever, which is 8,640 a day."""
    allowed = sum(limiter.check("1.2.3.4", now=100.0 + i * 120).allowed for i in range(10))
    assert allowed == settings.chat_rate_limit_per_day

    refused = limiter.check("1.2.3.4", now=9999.0)
    assert refused.scope == "client_day"
    assert refused.retry_after > 0, "must point at midnight, not at a second from now"


def test_many_clients_are_stopped_by_the_global_cap(limiter: ChatRateLimiter) -> None:
    """The limit that actually protects the quota. Per-client limits are only as
    good as client identification, and identification on the open internet is a
    best effort — a thousand addresses each staying under their own limit is the
    attack the other two cannot see."""
    allowed = sum(limiter.check(f"10.0.0.{i}", now=100.0 + i).allowed for i in range(40))
    assert allowed == settings.chat_global_limit_per_day

    refused = limiter.check("10.9.9.9", now=500.0)
    assert refused.scope == "global_day"
    assert "budget" in refused.detail
    assert "tomorrow" in refused.detail


def test_a_new_day_restores_the_allowance(limiter: ChatRateLimiter) -> None:
    for i in range(5):
        limiter.check("1.2.3.4", now=100.0 + i * 120)
    assert not limiter.check("1.2.3.4", now=1000.0).allowed

    # Roll the stored day back; the next check sees a new calendar day.
    limiter._clients["1.2.3.4"].day = dt.date(2000, 1, 1)
    limiter._global.day = dt.date(2000, 1, 1)
    assert limiter.check("1.2.3.4", now=2000.0).allowed


# ── the limiter's own bounds ─────────────────────────────────────────────────


def test_tracking_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unbounded dict keyed by client address is itself the memory exhaustion
    this module exists to prevent."""
    monkeypatch.setattr(settings, "rate_limit_max_tracked_clients", 10)
    limiter = ChatRateLimiter()
    for i in range(500):
        limiter.check(f"10.0.{i // 256}.{i % 256}", now=float(i))
    assert len(limiter._clients) <= 10


def test_disabling_the_limiter_allows_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "chat_rate_limit_enabled", False)
    limiter = ChatRateLimiter()
    assert all(limiter.check("1.2.3.4", now=float(i)).allowed for i in range(100))


# ── identifying the caller ───────────────────────────────────────────────────


def test_the_cloudflare_header_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """The service listens on 127.0.0.1 behind a tunnel, so the socket address is
    the tunnel for every request on earth. Without this every caller shares one
    bucket and the per-client limits are meaningless."""
    monkeypatch.setattr(settings, "client_ip_headers", "cf-connecting-ip,x-forwarded-for")
    assert client_key({"CF-Connecting-IP": "203.0.113.7"}, "127.0.0.1") == "203.0.113.7"


def test_a_forwarded_chain_uses_the_client_end() -> None:
    key = client_key({"X-Forwarded-For": "203.0.113.7, 70.41.3.18, 150.172.238.178"}, "127.0.0.1")
    assert key == "203.0.113.7"


def test_without_trusted_headers_only_the_socket_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Correct for a directly-reachable deployment, where the same header is pure
    client input and trusting it would hand every caller their own bucket."""
    monkeypatch.setattr(settings, "client_ip_headers", "")
    assert client_key({"CF-Connecting-IP": "203.0.113.7"}, "198.51.100.4") == "198.51.100.4"


def test_an_unidentifiable_caller_shares_one_bucket() -> None:
    assert client_key({}, None) == "unknown"


# ── request shape ────────────────────────────────────────────────────────────


def test_an_oversized_question_is_rejected(client: TestClient, override_session: None) -> None:
    body = {"question": "x" * (settings.chat_max_question_chars + 1), "history": []}
    assert client.post("/api/v1/chat", json=body).status_code == 422


def test_an_empty_question_is_rejected_by_the_schema(
    client: TestClient, override_session: None
) -> None:
    assert client.post("/api/v1/chat", json={"question": "", "history": []}).status_code == 422


def test_a_thousand_turn_history_is_rejected(client: TestClient, override_session: None) -> None:
    """`trim_history` discards everything past four turns, so this was never *used*.
    It was still received, validated and held in memory first, and that is the part
    the caller controls."""
    history = [{"role": "user", "content": "hi"}] * (settings.chat_max_history_turns + 1)
    body = {"question": "What is Japan's unemployment rate?", "history": history}
    assert client.post("/api/v1/chat", json=body).status_code == 422


def test_an_oversized_body_is_rejected_before_it_is_parsed(
    client: TestClient, override_session: None
) -> None:
    """The floor beneath the field limits: a 100 MB body should not be buffered and
    parsed only to be rejected field by field."""
    response = client.post(
        "/api/v1/chat",
        content=b"{}",
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(settings.max_request_bytes + 1),
        },
    )
    assert response.status_code == 413


# ── the limit as the endpoint enforces it ────────────────────────────────────


def test_the_endpoint_returns_429_with_a_retry_after(
    client: TestClient, override_session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "chat_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "chat_rate_limit_per_day", 100)
    monkeypatch.setattr(settings, "chat_global_limit_per_day", 100)
    monkeypatch.setattr(settings, "agent_enabled", False)  # never reach a provider
    monkeypatch.setattr(ratelimit, "_STORE", ChatRateLimiter())

    body = {"question": "What is Japan's unemployment rate?", "history": []}
    headers = {"CF-Connecting-IP": "203.0.113.99"}
    for _ in range(2):
        assert client.post("/api/v1/chat", json=body, headers=headers).status_code == 200

    blocked = client.post("/api/v1/chat", json=body, headers=headers)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert "Too many questions" in blocked.json()["detail"]


def test_the_streaming_route_is_limited_too(
    client: TestClient, override_session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Limiting one of the two spending routes limits nothing."""
    monkeypatch.setattr(settings, "chat_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "chat_rate_limit_per_minute", 1)
    monkeypatch.setattr(settings, "agent_enabled", False)
    monkeypatch.setattr(ratelimit, "_STORE", ChatRateLimiter())

    body = {"question": "What is Japan's unemployment rate?", "history": []}
    headers = {"CF-Connecting-IP": "203.0.113.50"}
    assert client.post("/api/v1/chat/stream", json=body, headers=headers).status_code == 200
    assert client.post("/api/v1/chat/stream", json=body, headers=headers).status_code == 429


def test_data_routes_are_not_rate_limited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The limit guards model quota. Rate-limiting the map would be all cost, no
    protection."""
    monkeypatch.setattr(settings, "chat_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "chat_rate_limit_per_minute", 1)
    monkeypatch.setattr(ratelimit, "_STORE", ChatRateLimiter())
    for _ in range(5):
        assert client.get("/health").status_code == 200


# ── telemetry ────────────────────────────────────────────────────────────────


def test_a_retraction_and_an_absence_are_counted_apart() -> None:
    """Both withhold a figure and only one means something went wrong. Merged, a
    rising retraction rate would read as the system working."""
    counters = ChatCounters()
    counters.record(ChatTrace(outcome="retracted", provider="mistral_agent"))
    counters.record(ChatTrace(outcome="absent"))
    counters.record(ChatTrace(outcome="answered", provider="mistral_agent", grounded=True))

    snapshot = counters.snapshot()
    assert snapshot["outcomes"] == {"retracted": 1, "absent": 1, "answered": 1}
    assert snapshot["refusal_rate"] == pytest.approx(2 / 3, abs=0.001)


def test_rates_are_reported_not_just_totals() -> None:
    """A count of retractions means nothing without a denominator, and reading one
    off a dashboard is how tolerances get misjudged."""
    counters = ChatCounters()
    counters.record(ChatTrace(outcome="answered", cached=True, seconds=1.0))
    counters.record(
        ChatTrace(outcome="answered", ranked=True, seconds=9.0, fallbacks=["mistral: rate limited"])
    )

    snapshot = counters.snapshot()
    assert snapshot["cache_hit_rate"] == 0.5
    assert snapshot["fallback_rate"] == 0.5
    assert snapshot["ranking_rate"] == 0.5
    assert snapshot["mean_seconds"] == 5.0


def test_an_empty_deployment_reports_no_rates_rather_than_zero() -> None:
    """Zero would read as "nothing ever falls back", which is a different claim
    from "nothing has been asked yet"."""
    snapshot = ChatCounters().snapshot()
    assert snapshot["requests"] == 0
    assert snapshot["fallback_rate"] is None


def test_the_trace_line_is_parseable_and_says_what_happened(caplog) -> None:
    import json
    import logging

    counters_before = telemetry.counters().requests
    with caplog.at_level(logging.INFO, logger="services.telemetry"):
        ChatTrace(
            provider="gemini_flash",
            tools=["rank_countries"],
            rows=5,
            ranked=True,
            countries_ranked=194,
            outcome="answered",
            grounded=True,
            seconds=6.9,
        ).emit()

    line = next(m for m in caplog.messages if m.startswith(telemetry.LOG_PREFIX))
    payload = json.loads(line[len(telemetry.LOG_PREFIX) + 1 :])
    assert payload["provider"] == "gemini_flash"
    assert payload["countries_ranked"] == 194
    assert payload["outcome"] == "answered"
    # And it reached the aggregate, not only the log.
    assert telemetry.counters().requests == counters_before + 1


def test_status_exposes_the_counters_without_exposing_a_caller(
    client: TestClient, override_session: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aggregates only. A question or an IP address in a public payload would be a
    privacy defect, not an observability feature."""
    import repositories

    async def zero(*_a, **_k):
        return 0

    for name in ("count_countries", "count_indicators", "count_observations", "count_anomalies"):
        monkeypatch.setattr(repositories, name, zero)
    monkeypatch.setattr(repositories, "list_sources", lambda *_a, **_k: _empty())

    body = client.get("/status").json()
    assert "chat" in body
    assert set(body["chat"]) >= {
        "requests",
        "outcomes",
        "daily_remaining",
        "tracked_clients",
        "chat_requests_today",
    }
    serialised = str(body["chat"])
    assert "203.0.113" not in serialised and "question" not in serialised


async def _empty():
    return []


# ── the single-worker assumption (decision #44) ──────────────────────────────


@pytest.mark.parametrize(
    ("argv", "env", "expected"),
    [
        (["uvicorn", "main:app"], {}, None),
        (["uvicorn", "main:app", "--workers", "4"], {}, 4),
        (["uvicorn", "main:app", "--workers=4"], {}, 4),
        (["gunicorn", "-w", "3", "main:app"], {}, 3),
        (["uvicorn", "main:app"], {"WEB_CONCURRENCY": "8"}, 8),
        (["uvicorn", "main:app", "--reload"], {}, None),
    ],
)
def test_the_worker_count_is_read_from_how_the_process_was_started(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], env: dict[str, str], expected: int | None
) -> None:
    """`--workers N` forks children that inherit argv, so reading our own command
    line covers the realistic case: somebody edits the systemd unit."""
    from services import singleflight

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert singleflight.detected_worker_count() == expected


def test_multiple_workers_produce_a_loud_warning(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """Three subsystems are per-process by choice and one of them — the rate
    limiter — is a security control. Its limits silently multiplying by the worker
    count is the failure this exists to make audible."""
    import logging

    from services import singleflight

    monkeypatch.setattr("sys.argv", ["uvicorn", "main:app", "--workers", "4"])
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    with caplog.at_level(logging.WARNING, logger="services.singleflight"):
        assert singleflight.warn_if_multi_worker() == 4

    message = " ".join(caplog.messages)
    assert "rate limit" in message.lower()
    assert "4x" in message


def test_a_single_worker_says_nothing(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """The normal case must be silent, or the warning stops being read."""
    import logging

    from services import singleflight

    monkeypatch.setattr("sys.argv", ["uvicorn", "main:app"])
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    with caplog.at_level(logging.WARNING, logger="services.singleflight"):
        assert singleflight.warn_if_multi_worker() is None
    assert not caplog.messages
