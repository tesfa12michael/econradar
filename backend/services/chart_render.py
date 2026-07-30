"""Server-side chart rendering for the VLM pipeline (feature 2.1).

Decision #9 chose *server-side rendering* over a client screenshot, because a
screenshot depends on browser state and viewport size and is therefore not
reproducible. That substance is preserved exactly. The renderer named alongside it
is not: see decision #25 — Kaleido 1.x no longer bundles Chromium and drives an
external headless Chrome per render, which on a 1 vCPU / 2 GB box already running
the API, five ingestion jobs and anomaly re-scoring is a memory risk for a
background panel, and Kaleido 0.2.1's bundled Chromium is unmaintained.
Matplotlib's Agg backend is a C library in-process: no browser, no subprocess, no
display, byte-identical output for identical input.

The chart is drawn in the design system's own palette rather than a default one.
That is not decoration — the VLM is asked to describe an image, and an image whose
forecast band is a different colour from the one on the page would produce a
description that does not match what the reader is looking at.
"""

from __future__ import annotations

import base64
import datetime as dt
import io
from typing import Any

import matplotlib

# Agg before pyplot: there is no display on the VPS, and the default backend would
# try to find one at import time.
matplotlib.use("Agg")

import matplotlib.pyplot as plt

from logging_config import get_logger

logger = get_logger(__name__)

BG_APP = "#0A0F1E"
BG_CARD = "#111827"
BORDER = "#1F2D45"
TEXT_PRIMARY = "#F0F4FF"
TEXT_SECONDARY = "#8B9EC7"
ACCENT = "#00D4FF"
ANOMALY = "#F59E0B"

#: features.md 2.1 specifies the last 36 points plus the forecast.
HISTORY_POINTS = 36


class ChartRenderError(RuntimeError):
    """Rendering failed. features.md 2.1 requires this be loud, never silent."""


def render_series_png(
    *,
    title: str,
    unit: str | None,
    history: list[tuple[dt.date, float]],
    forecast: list[tuple[dt.date, float, float, float]] | None = None,
    anomalies: list[tuple[dt.date, float]] | None = None,
) -> bytes:
    """Draw one series (with optional forecast band and markers) to a PNG.

    Raises rather than returning a blank image on failure: features.md 2.1 says
    "silent image-rendering failures must error loudly", and a VLM handed a blank
    canvas will describe one confidently.
    """
    if not history:
        raise ChartRenderError("cannot render a chart with no historical observations")

    recent = history[-HISTORY_POINTS:]
    try:
        figure, axes = plt.subplots(figsize=(9, 4.5), dpi=110)
        figure.patch.set_facecolor(BG_APP)
        axes.set_facecolor(BG_CARD)

        axes.plot(
            [d for d, _ in recent],
            [v for _, v in recent],
            color=ACCENT,
            linewidth=2.0,
            label="History",
        )

        if forecast:
            # The band is drawn joined to the last historical point, so the VLM sees
            # one continuous line rather than two disconnected series it might
            # describe as unrelated.
            last_date, last_value = recent[-1]
            dates = [last_date, *[d for d, _, _, _ in forecast]]
            medians = [last_value, *[m for _, m, _, _ in forecast]]
            lowers = [last_value, *[lo for _, _, lo, _ in forecast]]
            uppers = [last_value, *[up for _, _, _, up in forecast]]
            axes.plot(
                dates,
                medians,
                color=ACCENT,
                linewidth=2.0,
                linestyle="--",
                label="Forecast (median)",
            )
            axes.fill_between(dates, lowers, uppers, color=ACCENT, alpha=0.22, label="p10-p90 band")

        if anomalies:
            visible = [(d, v) for d, v in anomalies if d >= recent[0][0]]
            if visible:
                axes.scatter(
                    [d for d, _ in visible],
                    [v for _, v in visible],
                    color=ANOMALY,
                    s=46,
                    zorder=5,
                    label="Flagged observation",
                )

        axes.set_title(title, color=TEXT_PRIMARY, fontsize=13, pad=12)
        axes.set_ylabel(unit or "", color=TEXT_SECONDARY, fontsize=10)
        axes.tick_params(colors=TEXT_SECONDARY, labelsize=9)
        for spine in axes.spines.values():
            spine.set_color(BORDER)
        axes.grid(True, color=BORDER, linewidth=0.6, alpha=0.7)
        legend = axes.legend(
            facecolor=BG_CARD, edgecolor=BORDER, labelcolor=TEXT_SECONDARY, fontsize=9, loc="best"
        )
        legend.get_frame().set_alpha(0.9)
        figure.autofmt_xdate(rotation=30)
        figure.tight_layout()

        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", facecolor=figure.get_facecolor())
        plt.close(figure)
    except ChartRenderError:
        raise
    except Exception as exc:
        raise ChartRenderError(f"chart rendering failed: {type(exc).__name__}: {exc}") from exc

    payload = buffer.getvalue()
    if len(payload) < 1000:
        # A PNG this small is an empty canvas, whatever the library reported.
        raise ChartRenderError(f"rendered PNG is implausibly small ({len(payload)} bytes)")
    return payload


def render_series_b64(**kwargs: Any) -> str:
    """The same PNG, base64-encoded for an inline image part."""
    return base64.b64encode(render_series_png(**kwargs)).decode("ascii")
