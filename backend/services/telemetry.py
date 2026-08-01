"""What the agent actually did, per request and in aggregate (decision #45).

Two questions needed answering and neither could be, which is why this exists.
*Why was that answer wrong?* — needs one line per request carrying everything that
shaped it. *Is the system trustworthy and affordable at scale?* — needs counters,
because "it worked when I asked" is not a rate.

**The fields are chosen from real failures, not from what is easy to count.** Every
one of them is something that has already misled somebody in this project:

* `provider` and `fallbacks` — the Gemini handover failed for a day before anyone
  noticed, because the primary was answering and the fallback was only reached
  under rate limiting. A rising fallback rate is the early warning.
* `tools` and `rows` — an answer built on two rows describing a series of 481 was a
  real production defect (decision #32). Cost lives here too: tool calls are model
  turns.
* `ranked` — a superlative answered without a ranking is the Montenegro failure. It
  is refused in code, and the rate at which the refusal fires says whether the
  prompt is carrying its weight or the guard is doing all the work.
* `cached` — the hit rate is the difference between a free deployment and an
  exhausted quota.
* `outcome` — grounded, retracted, refused, timed out, or absent. **A retraction is
  a success of the verifier and a failure of the answer**, and the two must be
  counted separately or a rising retraction rate reads as the system working.
* `seconds` — the only number that says whether a person waited.

**In-process counters, deliberately.** Same trade as `services/ratelimit.py` and
`services/singleflight.py`: one uvicorn worker, so a dict is exact and free. They
reset on restart, which is honest — they describe this process, and the log lines
are the durable record. A real metrics backend is feature 2.6's job; this is the
signal it would collect, available now, and it costs one dict and one log line.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from logging_config import get_logger

logger = get_logger(__name__)

#: Emitted as the prefix of every per-request line so `journalctl -g chat_metric`
#: pulls exactly these and nothing else.
LOG_PREFIX = "chat_metric"


@dataclass(slots=True)
class ChatTrace:
    """One question's whole journey. Assembled as it happens, logged once at the end."""

    question_chars: int = 0
    provider: str | None = None
    model: str | None = None
    #: Providers that were tried and failed before the one that answered. Length is
    #: the fallback depth; an empty list means the primary answered.
    fallbacks: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    rows: int = 0
    countries_ranked: int = 0
    ranked: bool = False
    tool_failures: int = 0
    cached: bool = False
    grounded: bool = False
    groundedness: float | None = None
    derived_figures: int = 0
    outcome: str = "unknown"
    reason: str | None = None
    timed_out: bool = False
    seconds: float = 0.0

    def emit(self) -> None:
        """One structured line. JSON so it can be parsed later without a re-release."""
        payload = {k: v for k, v in asdict(self).items() if v not in (None, [], 0, 0.0, False)}
        payload.setdefault("outcome", self.outcome)
        logger.info("%s %s", LOG_PREFIX, json.dumps(payload, default=str, sort_keys=True))
        _COUNTERS.record(self)


class ChatCounters:
    """Aggregates for `/status`. Cheap enough to update on every request."""

    def __init__(self) -> None:
        self.outcomes: Counter[str] = Counter()
        self.providers: Counter[str] = Counter()
        self.requests = 0
        self.cache_hits = 0
        self.fallbacks = 0
        self.rankings = 0
        self.tool_calls = 0
        self.tool_failures = 0
        self.timeouts = 0
        self.total_seconds = 0.0

    def record(self, trace: ChatTrace) -> None:
        self.requests += 1
        self.outcomes[trace.outcome] += 1
        if trace.provider:
            self.providers[trace.provider] += 1
        self.cache_hits += int(trace.cached)
        self.fallbacks += int(bool(trace.fallbacks))
        self.rankings += int(trace.ranked)
        self.tool_calls += len(trace.tools)
        self.tool_failures += trace.tool_failures
        self.timeouts += int(trace.timed_out)
        self.total_seconds += trace.seconds

    def snapshot(self) -> dict[str, Any]:
        """Rates, not just totals — a count of retractions means nothing without a
        denominator, and reading one off a dashboard is how tolerances get misjudged."""
        n = self.requests
        return {
            "requests": n,
            "outcomes": dict(self.outcomes),
            "providers": dict(self.providers),
            "cache_hit_rate": round(self.cache_hits / n, 3) if n else None,
            "fallback_rate": round(self.fallbacks / n, 3) if n else None,
            "ranking_rate": round(self.rankings / n, 3) if n else None,
            "refusal_rate": round(
                (self.outcomes["refused"] + self.outcomes["retracted"] + self.outcomes["absent"])
                / n,
                3,
            )
            if n
            else None,
            "timeout_rate": round(self.timeouts / n, 3) if n else None,
            "mean_seconds": round(self.total_seconds / n, 2) if n else None,
            "tool_calls": self.tool_calls,
            "tool_failures": self.tool_failures,
        }

    def reset(self) -> None:
        """Tests only."""
        self.__init__()


_COUNTERS = ChatCounters()


def counters() -> ChatCounters:
    return _COUNTERS
