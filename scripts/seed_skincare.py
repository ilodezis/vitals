#!/usr/bin/env python3
import asyncio
from datetime import date, timedelta
from vitals.config import load_config
from vitals.database import create_session_factory
from vitals.services import skincare_service

async def main():
    config = load_config()
    factory = create_session_factory(config)
    
    # We will populate dates from 2026-06-04 to 2026-06-22 (today).
    #
    # Schedule:
    # - Пилинг (peel): Tuesdays (2) and Saturdays (6)
    # - Дифферин (retinoid): Mondays (1), Wednesdays (3), Thursdays (4), Fridays (5), Sundays (0)
    # - Азелик (azelaic): Mondays (1), Wednesdays (3), Thursdays (4), Fridays (5), Sundays (0)
    # - Сыворотка с ниацинамидом и цинком + SPF (niacinamide_spf): daily
    # - Крем (moisturizer): daily
    
    start_date = date(2026, 6, 4)
    end_date = date(2026, 6, 22)
    
    async with factory() as session:
        # First, clear any existing skincare logs to avoid duplicates / conflicts
        from sqlalchemy import delete
        from vitals.models.skincare import SkincareLog
        await session.execute(delete(SkincareLog))
        
        current = start_date
        while current <= end_date:
            dow = int(current.strftime("%w"))  # 0 = Sunday, 1 = Monday, ..., 6 = Saturday
            
            is_peel = dow in (2, 6)
            is_retinoid = dow in (1, 3, 4, 5, 0)
            is_azelaic = dow in (1, 3, 4, 5, 0)
            is_niacinamide_spf = True
            is_moisturizer = True
            
            # For 2026-06-04, the user's history shows false for washing/serum.
            # But let's log the scheduled items anyway.
            await skincare_service.upsert_log(
                session,
                on_date=current,
                retinoid=is_retinoid,
                azelaic=is_azelaic,
                peel=is_peel,
                niacinamide_spf=is_niacinamide_spf,
                moisturizer=is_moisturizer,
                override=True
            )
            current += timedelta(days=1)
        
        await session.commit()
        print("Skincare logs seeded successfully.")

if __name__ == "__main__":
    asyncio.run(main())
