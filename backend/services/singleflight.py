"""One expensive computation per key, however many callers ask for it at once.

The country profile page fires four AI panels in parallel, and a country that has
just fallen out of cache is usually rediscovered by several visitors within the
same few seconds — a link is shared, a crawler sweeps, someone reloads. Without
coordination each of those is a separate Modal call or a separate provider
completion for an answer that is identical by construction, because the cache key
is content-addressed (decision #31): same key, same inputs, same output.

So callers coalesce. The first caller for a key runs the work; everyone else
awaits the same future and receives the same result. A failure propagates to all
waiters rather than leaving some of them to retry in a thundering herd, and the
entry is removed either way so the next request after a failure is free to try
again.

**Scope, stated plainly:** these are in-process `asyncio` primitives and they
coordinate one event loop. The service runs a single uvicorn worker
(`uvicorn main:app` with no `--workers`), so that is the whole process and the
guarantee holds. See `warn_if_multi_worker` at the bottom of this file for what
happens if that ever stops being true, and decision #44 for why the constraint is
detected rather than removed.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from logging_config import get_logger

logger = get_logger(__name__)

#: key -> the task computing it. Present only while a computation is in flight.
_in_flight: dict[str, asyncio.Task[Any]] = {}


def is_in_flight(key: str) -> bool:
    """Whether some caller is already computing `key` right now."""
    task = _in_flight.get(key)
    return task is not None and not task.done()


async def run[T](key: str, factory: Callable[[], Awaitable[T]]) -> T:
    """Run `factory()` once per key; concurrent callers share the one result.

    `factory` is a callable rather than a coroutine so that the duplicate callers
    never construct one — an un-awaited coroutine would emit a RuntimeWarning and,
    worse, suggest the work had been started when it had not.
    """
    existing = _in_flight.get(key)
    if existing is not None and not existing.done():
        logger.debug("single-flight: joining in-flight computation for %s", key)
        # shield: a client disconnecting cancels *its* await, and must not cancel
        # the shared computation that other waiters are still depending on.
        return await asyncio.shield(existing)

    task: asyncio.Task[T] = asyncio.create_task(factory())
    _in_flight[key] = task
    try:
        return await asyncio.shield(task)
    finally:
        # Only clear our own entry: a later caller may already have installed a
        # fresh task under this key after ours completed.
        if _in_flight.get(key) is task:
            _in_flight.pop(key, None)


async def await_in_flight(key: str, *, timeout: float, appear_within: float = 0.0) -> Any | None:
    """Wait for an already-running computation, or return None.

    This is the half of single-flight that lets one panel benefit from another's
    work **without ever starting that work itself**. Narration wants the forecast
    the forecast panel is computing at that moment; it does not want to trigger a
    cold GPU call of its own if nobody asked for one (decision #31).

    `appear_within` exists because checking once loses a race that happens on every
    real page load. The browser fires all four panels together, and whether the
    forecast has registered its task by the time narration looks is a coin toss
    decided by two database round trips. Observed live on a cold country: the
    forecast computed, narration missed it, and narration cached a version with no
    forecast that the next visitor would immediately supersede. A short grace period
    for the task to *appear* costs nothing when nobody is computing.
    """
    deadline = asyncio.get_running_loop().time() + appear_within
    while True:
        task = _in_flight.get(key)
        if task is not None and not task.done():
            break
        if asyncio.get_running_loop().time() >= deadline:
            return None
        await asyncio.sleep(0.05)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except TimeoutError:
        logger.info("single-flight: gave up waiting %.1fs for %s", timeout, key)
        return None
    except Exception:
        # The owner logs and handles its own failure; a bystander just proceeds
        # without the result it was hoping to borrow.
        return None


# ── the single-worker assumption, made loud (decision #44) ───────────────────


def detected_worker_count() -> int | None:
    """How many workers this process was started with, if it can be told.

    `--workers N` forks children that inherit the parent's `argv`, and gunicorn's
    `-w` behaves the same way, so reading our own command line covers the realistic
    case: somebody edits the systemd unit. `WEB_CONCURRENCY` is checked because it
    is the convention both honour without a flag. None means "cannot tell", which is
    reported as exactly that rather than as one.
    """
    concurrency = os.environ.get("WEB_CONCURRENCY", "").strip()
    if concurrency.isdigit():
        return int(concurrency)

    argv = sys.argv
    for index, token in enumerate(argv):
        if token in ("--workers", "-w") and index + 1 < len(argv) and argv[index + 1].isdigit():
            return int(argv[index + 1])
        if token.startswith("--workers=") and token.partition("=")[2].isdigit():
            return int(token.partition("=")[2])
    return None


def warn_if_multi_worker() -> int | None:
    """Say so, loudly, if three safety properties have quietly stopped holding.

    Three subsystems are in-process by deliberate choice, and each degrades
    differently under `--workers N`:

    * **this module** — coalescing becomes one-per-worker, so a cold country can
      cost N GPU calls instead of one. Wasteful, not wrong.
    * **`services/telemetry.py`** — `/status` reports one worker's counters, so
      every rate is computed over a fraction of the traffic. Misleading.
    * **`services/ratelimit.py`** — each worker enforces its own copy, so the
      effective limits multiply by N. **That one is a security control**, and it
      failing quietly is the reason this function exists at all.

    Deliberately a warning rather than a refusal to start. A deployment that adds
    workers is usually responding to load, and taking the site down to make a point
    about rate-limit arithmetic would be the worse outcome — the operator needs to
    be told, not overruled. The upgrade path, when it is needed: move the limiter
    and the counters behind Postgres (a counter table with an upsert per request is
    a ~10 ms write against a request that takes seconds), and single-flight behind a
    Postgres advisory lock. The lock is deliberately *not* used today because it
    would hold a pooled connection for the length of a cold GPU call on a 1 vCPU
    box; that objection is about the GPU call, not about the lock, so it does not
    extend to the limiter.
    """
    workers = detected_worker_count()
    if workers is not None and workers > 1:
        logger.warning(
            "Started with %d workers. Single-flight coalescing, the chat rate limiter "
            "and the /status counters are all per-process: coalescing becomes "
            "one-per-worker, the reported rates cover ~1/%d of traffic, and the "
            "effective chat rate limits are %dx what is configured. See "
            "services/singleflight.py:warn_if_multi_worker.",
            workers,
            workers,
            workers,
        )
    return workers
