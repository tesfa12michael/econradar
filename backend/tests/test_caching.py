"""Lazy, content-addressed caching and single-flight (decision #31).

The waste these pin down was measured, not theorised. Chart analysis held two
cache keys per series because the key changes when a forecast warms, and every
panel re-generated on a TTL boundary even though the key — and therefore the
inputs, and therefore the answer — had not changed at all.
"""

from __future__ import annotations

import asyncio

import pytest


async def test_concurrent_callers_share_one_execution():
    """Five visitors opening the same country page must cost one generation."""
    from services import singleflight

    calls = 0

    async def expensive():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return "generated once"

    results = await asyncio.gather(*(singleflight.run("k", expensive) for _ in range(5)))
    assert calls == 1
    assert results == ["generated once"] * 5


async def test_a_failure_is_not_cached_as_an_answer():
    """The entry clears on failure, so the next request may try again rather than
    inheriting somebody else's exception forever."""
    from services import singleflight

    async def boom():
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError):
        await singleflight.run("k2", boom)
    assert not singleflight.is_in_flight("k2")

    async def fine():
        return "recovered"

    assert await singleflight.run("k2", fine) == "recovered"


async def test_borrowing_never_starts_work_of_its_own():
    """The chart-analysis panel waits for a forecast that is already running and
    otherwise proceeds without one — it must never trigger a cold GPU itself."""
    from services import singleflight

    assert await singleflight.await_in_flight("cold", timeout=0.01) is None

    async def slow():
        await asyncio.sleep(0.05)
        return "forecast"

    task = asyncio.create_task(singleflight.run("warm", slow))
    await asyncio.sleep(0)  # let it register
    assert await singleflight.await_in_flight("warm", timeout=1.0) == "forecast"
    await task


async def test_a_waiter_giving_up_does_not_cancel_the_shared_work():
    """A client disconnecting cancels its own await. The computation the others are
    still depending on has to survive it."""
    from services import singleflight

    finished = False

    async def slow():
        nonlocal finished
        await asyncio.sleep(0.1)
        finished = True
        return "done"

    owner = asyncio.create_task(singleflight.run("shared", slow))
    await asyncio.sleep(0)
    impatient = asyncio.create_task(singleflight.run("shared", slow))
    await asyncio.sleep(0.01)
    impatient.cancel()
    assert await owner == "done"
    assert finished


def test_the_cache_key_carries_the_prompt_revision():
    """Bumping the revision must retire every existing entry, or a prompt fix never
    reaches text already generated."""
    from services import cache

    before = cache.build_cache_key("vlm_interpretation", country="BRA", indicator="CBPOL")
    original = cache.PROMPT_REVISION
    try:
        cache.PROMPT_REVISION = original + 1
        assert (
            cache.build_cache_key("vlm_interpretation", country="BRA", indicator="CBPOL") != before
        )
    finally:
        cache.PROMPT_REVISION = original


async def test_borrowing_waits_briefly_for_the_task_to_appear():
    """The race this closes was live, not hypothetical.

    The panels are fired together by the browser, so whether the forecast has
    registered its task by the time chart analysis looks is decided by a couple of
    database round trips. Checking once loses that race routinely — observed on a
    cold country: the forecast computed, the borrower missed it and cached a
    version with no forecast that the very next visitor would supersede.
    """
    from services import singleflight

    async def slow():
        await asyncio.sleep(0.05)
        return "forecast"

    async def start_late():
        await asyncio.sleep(0.08)  # registers *after* the borrower first looks
        return await singleflight.run("late", slow)

    owner = asyncio.create_task(start_late())
    borrowed = await singleflight.await_in_flight("late", timeout=2.0, appear_within=1.0)
    assert borrowed == "forecast"
    await owner


async def test_borrowing_still_gives_up_when_nobody_is_computing():
    """The grace period must not become a stall on a series nobody asked about."""
    from services import singleflight

    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await singleflight.await_in_flight("nobody", timeout=5.0, appear_within=0.2) is None
    assert loop.time() - started < 1.0
