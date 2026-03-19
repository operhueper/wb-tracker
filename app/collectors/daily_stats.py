import json
import logging
from datetime import date, timedelta

from app import database as db
from app.wb_api.client import WBClient
from app.wb_api import advert as adv

logger = logging.getLogger(__name__)


async def collect_daily_stats(client: WBClient, days_back: int = 1):
    """
    Fetch statistics for the past `days_back` days.
    By default runs for yesterday (days_back=1). If 30, gets 30 days.
    """
    today = date.today()
    end_date = today.isoformat()
    begin_date = (today - timedelta(days=days_back)).isoformat()
    
    logger.info(f"📊 Stats collection from {begin_date} to {end_date}")

    try:
        campaigns = await db.fetch("SELECT wb_campaign_id FROM campaigns")
        if not campaigns:
            logger.warning("No campaigns in DB yet")
            return

        campaign_ids = [r["wb_campaign_id"] for r in campaigns]
        logger.info(f"Fetching stats for {len(campaign_ids)} campaigns")

        chunk_size = 50
        for i in range(0, len(campaign_ids), chunk_size):
            chunk = campaign_ids[i : i + chunk_size]
            stats_list = await adv.get_fullstats(client, chunk, begin_date, end_date)

            if not stats_list:
                continue

            for stat in stats_list:
                wb_id = stat.get("advertId")
                days = stat.get("days", [])

                for day_data in days:
                    try:
                        stat_date = day_data.get("date", "")[:10]  # Get YYYY-MM-DD
                        if not stat_date:
                            continue

                        apps = day_data.get("apps", [])
                        # Sum across all placement types
                        shows = sum(a.get("views", 0) for a in apps)
                        clicks = sum(a.get("clicks", 0) for a in apps)
                        spend = sum(a.get("sum", 0.0) for a in apps)
                        orders = sum(a.get("orders", 0) for a in apps)
                        orders_sum = sum(a.get("sum_price", 0.0) for a in apps)

                        ctr = round(clicks / shows * 100, 4) if shows > 0 else 0
                        cpc = round(spend / clicks, 2) if clicks > 0 else 0
                        cpo = round(spend / orders, 2) if orders > 0 else 0
                        drr = round(spend / orders_sum * 100, 4) if orders_sum > 0 else 0
                        cr = round(orders / clicks * 100, 4) if clicks > 0 else 0

                        camp_uuid = await db.fetchval(
                            "SELECT id FROM campaigns WHERE wb_campaign_id = $1", wb_id
                        )
                        if not camp_uuid:
                            continue

                        await db.execute(
                            """
                            INSERT INTO campaign_daily_stats
                              (campaign_id, wb_campaign_id, stat_date,
                               shows, clicks, ctr, cpc, spend,
                               orders, orders_sum, cpo, drr, cr, raw_data)
                            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                            ON CONFLICT (wb_campaign_id, stat_date) DO UPDATE SET
                              shows = EXCLUDED.shows,
                              clicks = EXCLUDED.clicks,
                              ctr = EXCLUDED.ctr,
                              cpc = EXCLUDED.cpc,
                              spend = EXCLUDED.spend,
                              orders = EXCLUDED.orders,
                              orders_sum = EXCLUDED.orders_sum,
                              cpo = EXCLUDED.cpo,
                              drr = EXCLUDED.drr,
                              cr = EXCLUDED.cr,
                              raw_data = EXCLUDED.raw_data
                            """,
                            camp_uuid, wb_id, stat_date,
                            shows, clicks, ctr, cpc, spend,
                            orders, orders_sum, cpo, drr, cr,
                            json.dumps(day_data),
                        )

                    except Exception as e:
                        logger.error(f"Error saving stats for campaign {wb_id} on {stat_date}: {e}")

        logger.info(f"✅ Daily stats collection done ({days_back} days)")

    except Exception as e:
        logger.error(f"Daily stats collection failed: {e}", exc_info=True)
