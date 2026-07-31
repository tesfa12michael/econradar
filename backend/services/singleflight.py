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
guarantee holds. Adding workers would silently reduce this to one-per-worker
rather than one globally; the upgrade path is a Postgres advisory lock keyed on
the same string, which is deliberately *not* used today because it would hold a
pooled connection open for the length of a cold GPU call on a 1 vCPU box.
"""

from __future__ import annotations

import asyncio
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
