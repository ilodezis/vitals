#!/usr/bin/env python3
"""Re-parse already-stored Garmin raw payloads with the current parser.

Runs 1/4/5 of the Garmin capture expansion (sleep detail, intraday stress/
Body Battery, minute-level sleep series) all read fields out of
get_sleep_data/get_stress_data responses that Garmin was already sending in
full — the old parser just discarded most of it. That means every day ever
synced already has the raw JSON these fields need, sitting untouched in
raw_payloads. Same story for an activity's elevation/power/training-effect
(run 3): those are on the activity summary Garmin always returns, not the new
per-activity detail call. So all of that is recoverable for the *entire*
history with zero new Garmin API calls — this script just re-runs
ingest_daily/ingest_activities against the payload already on disk.

NOT recovered here (need a live Garmin call, not just a reparse):
  - training_status (run 2) — get_training_status was never fetched before
    today, so it's simply absent from old raw payloads.
  - per-activity hr_zone_seconds/splits (run 3) — need
    fetch_activity_details(activity_id), one call per historical activity.
Backfilling those means a real resync (garmin_service.sync(days=N), or a
purpose-built loop over historical activity ids) with the rate-limit caution
the original plan called out — deliberately not attempted here.

Run inside the app container so VITALS_DATABASE_URL is already the real one:
    docker exec vitals_app python scripts/backfill_garmin_reparse.py --stats
    docker exec vitals_app python scripts/backfill_garmin_reparse.py --limit 3
    docker exec vitals_app python scripts/backfill_garmin_reparse.py
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from vitals.config import load_config
from vitals.database import create_session_factory
from vitals.models.garmin import DOMAIN
from vitals.models.raw_payload import RawPayload
from vitals.services import garmin_service


async def _stats(session) -> None:
    daily = (await session.execute(
        select(RawPayload).where(RawPayload.domain == DOMAIN, RawPayload.external_id.startswith("daily:"))
        .order_by(RawPayload.external_id)
    )).scalars().all()
    activities = (await session.execute(
        select(RawPayload).where(RawPayload.domain == DOMAIN, RawPayload.external_id.startswith("activity:"))
    )).scalars().all()
    span = f"{daily[0].external_id} .. {daily[-1].external_id}" if daily else "—"
    print(f"daily payloads:    {len(daily)}  ({span})")
    print(f"activity payloads: {len(activities)}")


async def _run(limit: int | None, batch: int) -> None:
    config = load_config()
    session_factory = create_session_factory(config)

    async with session_factory() as session:
        daily_rows = (await session.execute(
            select(RawPayload).where(RawPayload.domain == DOMAIN, RawPayload.external_id.startswith("daily:"))
            .order_by(RawPayload.external_id)
        )).scalars().all()
        if limit:
            daily_rows = daily_rows[:limit]

        for i, raw_row in enumerate(daily_rows, 1):
            await garmin_service.reparse_daily_from_raw(session, raw_row)
            if i % batch == 0:
                await session.commit()
                print(f"  days: {i}/{len(daily_rows)}")
        await session.commit()
        print(f"done: {len(daily_rows)} daily payloads reparsed")

        activity_rows = (await session.execute(
            select(RawPayload).where(RawPayload.domain == DOMAIN, RawPayload.external_id.startswith("activity:"))
        )).scalars().all()
        if limit:
            activity_rows = activity_rows[:limit]

        for i, raw_row in enumerate(activity_rows, 1):
            await garmin_service.reparse_activity_from_raw(session, raw_row)
            if i % batch == 0:
                await session.commit()
                print(f"  activities: {i}/{len(activity_rows)}")
        await session.commit()
        print(f"done: {len(activity_rows)} activity payloads reparsed")


async def _main_async(args: argparse.Namespace) -> None:
    if args.stats:
        config = load_config()
        session_factory = create_session_factory(config)
        async with session_factory() as session:
            await _stats(session)
        return
    await _run(args.limit, args.batch)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stats", action="store_true", help="count only, no writes")
    parser.add_argument("--limit", type=int, default=None, help="cap rows processed per kind (smoke test)")
    parser.add_argument("--batch", type=int, default=20, help="commit every N rows (default 20)")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
