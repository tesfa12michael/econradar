"""Thin async wrapper over the deployed Modal functions (decision #21).

Isolated behind one module for three reasons: `modal` is imported lazily so a
missing or misconfigured SDK degrades the cascade instead of breaking app import;
the credential requirement is documented in exactly one place; and tests can
substitute a fake without touching `ForecastingService`.

Credentials come from the **process environment** (`MODAL_TOKEN_ID` /
`MODAL_TOKEN_SECRET`), placed there by the systemd drop-in
`/etc/systemd/system/econradar.service.d/10-modal.conf`. They are deliberately not
in `backend/.env`: pydantic-settings reads that file into `Settings` without ever
populating `os.environ`, which is the only place the `modal` library looks. See
PROGRESS.md, "Phase 3 prep — Modal".
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from config import settings
from logging_config import get_logger

logger = get_logger(__name__)


class ModalUnavailable(RuntimeError):
    """Modal could not be reached, is not configured, or the function is not deployed."""


def is_configured() -> bool:
    """True when the process environment carries Modal credentials.

    Checked before calling rather than after failing, so an unconfigured
    environment produces one clear log line instead of an authentication traceback
    on every cascade step.
    """
    return bool(os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET"))


_functions: dict[str, Any] = {}


def _lookup(function_name: str) -> Any:
    """Resolve (and memoise) a deployed Modal function handle."""
    if function_name in _functions:
        return _functions[function_name]
    try:
        import modal
    except ImportError as exc:  # pragma: no cover - modal is a declared dependency
        raise ModalUnavailable(f"modal SDK not importable: {exc}") from exc

    try:
        handle = modal.Function.from_name(settings.modal_app_name, function_name)
    except Exception as exc:
        raise ModalUnavailable(
            f"Modal function {settings.modal_app_name}/{function_name} not found: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    _functions[function_name] = handle
    return handle


async def call(function_name: str, *args: Any) -> dict:
    """Invoke a deployed Modal function, raising ModalUnavailable on any failure.

    Every failure mode — not configured, not deployed, timed out, errored remotely —
    is collapsed into one exception type, because the caller's response to all of
    them is identical: log it and try the next model in the cascade.
    """
    if not settings.modal_enabled:
        raise ModalUnavailable("Modal calls are disabled (MODAL_ENABLED=false).")
    if not is_configured():
        raise ModalUnavailable(
            "MODAL_TOKEN_ID / MODAL_TOKEN_SECRET are absent from the process "
            "environment — see the systemd drop-in, not backend/.env."
        )

    handle = _lookup(function_name)
    try:
        return await asyncio.wait_for(
            handle.remote.aio(*args), timeout=settings.modal_timeout_seconds
        )
    except TimeoutError as exc:
        raise ModalUnavailable(
            f"{function_name} exceeded {settings.modal_timeout_seconds}s "
            "(a cold GPU container may still be starting)"
        ) from exc
    except Exception as exc:
        raise ModalUnavailable(f"{function_name} failed: {type(exc).__name__}: {exc}") from exc
