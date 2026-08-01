"""Per-client and whole-deployment limits for the chat endpoint (decision #43).

`POST /api/v1/chat` is public, unauthenticated, and costs two to three model turns
against a free-tier quota on every cache miss. Nothing stood between a `while true`
loop and the providers. This module is what stands there.

**Three limits, because they fail differently.**

* **Burst, per client.** Stops a script before it warms up. Cheap to evaluate and
  the only one a human will ever notice.
* **Daily, per client.** Stops a patient script. A burst limit alone permits six
  requests a minute forever, which is 8,640 a day.
* **Daily, whole deployment.** The one that actually protects the quota, because
  the two above are only as good as client identification — and client
  identification on the open internet is a best effort, not a fact. If a thousand
  addresses each stay under their limit, this is what still says no.

**Identifying the client.** The service listens on 127.0.0.1 behind a Cloudflare
Tunnel, so the socket address is the tunnel for every request on earth. The real
address arrives in `CF-Connecting-IP`, which Cloudflare *overwrites* rather than
appends, so a client cannot forge it through the tunnel. The header list is a
setting, and an empty list means trust nothing but the socket — which is the
correct configuration for a deployment that is directly reachable, where the same
header would be pure client input.

**In-process, deliberately** (see decision #44 and `services/singleflight.py` for
the same trade in a different place). One uvicorn worker runs today, so a dict is
exact, costs no network hop, and cannot fail. Under `--workers N` each worker would
enforce its own copy and the effective limits would multiply by N; the fix is to
swap `_STORE` for a shared backend, which is why the counting lives behind one
object rather than being scattered through the middleware.

**The limiter is bounded too.** An unbounded dict keyed by client address is itself
a memory-exhaustion vector on a public endpoint — the shape of attack this module
exists to stop. Tracking is capped and the oldest-seen clients are evicted.
"""

from __future__ import annotations

import datetime as dt
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from config import settings
from logging_config import get_logger

logger = get_logger(__name__)

GLOBAL_KEY = "*"


@dataclass(frozen=True, slots=True)
class Decision:
    """Whether this request may proceed, and what to tell the caller if not."""

    allowed: bool
    #: Which limit stopped it — logged and returned, because "you are rate limited"
    #: without saying which limit is unactionable for a legitimate caller.
    scope: str = ""
    retry_after: int = 0

    @property
    def detail(self) -> str:
        if self.allowed:
            return ""
        if self.scope == "global_day":
            return (
                "EconRadar's daily budget for AI answers is used up. The map, country "
                "pages and rankings are unaffected — try the chat again tomorrow."
            )
        window = "minute" if self.scope == "client_minute" else "day"
        return f"Too many questions from this address in one {window}. Try again shortly."


@dataclass(slots=True)
class _Client:
    """One caller's recent history. `hits` is a window, `day_count` is a counter."""

    hits: deque[float] = field(default_factory=deque)
    day: dt.date | None = None
    day_count: int = 0


class ChatRateLimiter:
    """Sliding-window burst + calendar-day counters, per client and overall.

    Calendar days rather than rolling 24-hour windows on purpose: a rolling window
    needs every timestamp of the day retained per client, which is the memory this
    class is trying not to spend. A caller who exhausts the day at 23:00 gets a
    fresh allowance at midnight UTC, and that is an acceptable, explainable edge.
    """

    def __init__(self) -> None:
        # Ordered so eviction is oldest-seen-first without a scan.
        self._clients: OrderedDict[str, _Client] = OrderedDict()
        self._global = _Client()

    def check(self, client_key: str, *, now: float | None = None) -> Decision:
        """Evaluate every limit. Counts the request only if it is allowed.

        A rejected request must not consume allowance, or a client held at the limit
        would never recover — the rejections themselves would keep the window full.
        """
        if not settings.chat_rate_limit_enabled:
            return Decision(allowed=True)

        now = time.monotonic() if now is None else now
        today = dt.datetime.now(dt.UTC).date()

        client = self._clients.get(client_key)
        if client is None:
            client = _Client()
            self._evict_if_full()
        self._clients[client_key] = client
        self._clients.move_to_end(client_key)

        self._roll_day(client, today)
        self._roll_day(self._global, today)
        self._expire(client.hits, now)

        if self._global.day_count >= settings.chat_global_limit_per_day:
            return self._refuse("global_day", client_key, _seconds_to_utc_midnight())
        if client.day_count >= settings.chat_rate_limit_per_day:
            return self._refuse("client_day", client_key, _seconds_to_utc_midnight())
        if len(client.hits) >= settings.chat_rate_limit_per_minute:
            retry = max(1, int(60 - (now - client.hits[0])) + 1)
            return self._refuse("client_minute", client_key, retry)

        client.hits.append(now)
        client.day_count += 1
        self._global.day_count += 1
        return Decision(allowed=True)

    # ── internals ────────────────────────────────────────────────────────────

    def _refuse(self, scope: str, client_key: str, retry_after: int) -> Decision:
        logger.warning(
            "chat rate limit: scope=%s client=%s retry_after=%ds", scope, client_key, retry_after
        )
        return Decision(allowed=False, scope=scope, retry_after=retry_after)

    @staticmethod
    def _expire(hits: deque[float], now: float) -> None:
        while hits and now - hits[0] >= 60.0:
            hits.popleft()

    @staticmethod
    def _roll_day(target: _Client, today: dt.date) -> None:
        if target.day != today:
            target.day, target.day_count = today, 0

    def _evict_if_full(self) -> None:
        while len(self._clients) >= settings.rate_limit_max_tracked_clients:
            evicted, _ = self._clients.popitem(last=False)
            logger.info("rate limiter evicted the oldest tracked client (%s)", evicted)

    def snapshot(self) -> dict[str, int]:
        """Counters for `/status`. Cheap, and the only view anyone has of this.

        `chat_requests_today` is deliberately not called "answers": the limiter runs
        as a route dependency, before the body is validated, so a request that is
        allowed through and then rejected as malformed still counted. That is the
        right behaviour — a client spamming bad JSON is still traffic — but it means
        this number is *requests admitted*, and reading it as answers given would
        overstate what the quota was spent on.
        """
        today = dt.datetime.now(dt.UTC).date()
        used = self._global.day_count if self._global.day == today else 0
        return {
            "tracked_clients": len(self._clients),
            "chat_requests_today": used,
            "daily_budget": settings.chat_global_limit_per_day,
            "daily_remaining": max(0, settings.chat_global_limit_per_day - used),
        }

    def reset(self) -> None:
        """Tests only. Production has one limiter for the process lifetime."""
        self._clients.clear()
        self._global = _Client()


#: One limiter per process. Swapping this for a shared implementation is the whole
#: multi-worker change; nothing else here knows where the counters live.
_STORE = ChatRateLimiter()


def limiter() -> ChatRateLimiter:
    return _STORE


def client_key(headers: dict[str, str] | None, socket_host: str | None) -> str:
    """The best available identity for a caller.

    Falls back to the socket address, and to a single shared bucket if even that is
    missing — an unidentifiable caller sharing one allowance is the safe default,
    because the alternative is an unidentifiable caller having no limit at all.
    """
    lowered = {k.lower(): v for k, v in (headers or {}).items()}
    for header in settings.client_ip_header_list:
        value = lowered.get(header, "")
        if value:
            # X-Forwarded-For is a chain; the client is the first entry.
            return value.split(",")[0].strip()
    return socket_host or "unknown"


def _seconds_to_utc_midnight() -> int:
    now = dt.datetime.now(dt.UTC)
    midnight = dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC)
    return max(1, int((midnight - now).total_seconds()))
