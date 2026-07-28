"""One-off World Bank ingest — populates Supabase and proves the pipeline end to end.

Run from the backend/ directory with DATABASE_URL configured (env or backend/.env):

    python scripts/smoke_ingest.py

Fetches the configured focus-country indicators, writes them to time_series (and a
pipeline_runs row), and prints the result. After it succeeds, hit
GET /api/v1/indicators/NGA?code=NY.GDP.MKTP.KD.ZG to see the data served back.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running as `python scripts/smoke_ingest.py` from the backend/ dir.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings  # noqa: E402
from connectors import WorldBankConnector  # noqa: E402


async def main() -> int:
    if not settings.database_url:
        print("ERROR: DATABASE_URL is not set — nothing to ingest into.", file=sys.stderr)
        return 1
    connector = WorldBankConnector()
    result = await connector.run()
    print(
        f"World Bank ingest: status={result.status} fetched={result.records_fetched} "
        f"inserted={result.records_inserted} failed={result.records_failed} "
        f"skipped={result.records_skipped}"
    )
    return 0 if result.status in ("success", "partial") else 2


if __name__ == "__main__":
    if sys.platform == "win32":
        # psycopg3's async driver rejects Windows' default ProactorEventLoop;
        # the selector loop is required for local runs (production runs on Linux).
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(asyncio.run(main()))
