import json
import logging
from datetime import date, timedelta

from app import database as db
from app.wb_api.client import WBClient
from app.wb_api import advert as adv

logger = logging.getLogger(__name__)


async def collect_daily_stats(client: WBClient):
    """
    Daily at 06:00 MSK:
    - Fetch yesterday's statistics for all known campaigns
    - Calculate CTR, CPO, DRR, CR
    - Save to campaign_daily_stats
    """
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    logger.info(f"📊 Daily stats collection for {yesterday}")

    try:
        campaigns = await db.fetch("SELECT wb_campaign_id FROM campaigns")
        if not campaigns:
            logger.warning("No campaigns in DB yet")
            return

        campaign_ids = [r["wb_campaign_id"] for r in campaigns]
        logger.info(f"Fetching stats for {len(campaign_ids)} campaigns")

        # WB fullstats accepts up to 100 campaigns per request
        chunk_size = 50
        for i in range(0, len(campaign_ids), chunk_size):
            chunk = campaign_ids[i : i + chunk_size]
            stats_list = await adv.get_fullstats(client, chunk, [yesterday])

            for stat in stats_list:
                wb_id = stat.get("advertId")
                days = stat.get("days", [])

                for day_data in days:
                    try:
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
                            camp_uuid, wb_id, yesterday,
                            shows, clicks, ctr, cpc, spend,
                            orders, orders_sum, cpo, drr, cr,
                            json.dumps(day_data),
                        )

                        logger.info(
                            f"  Campaign {wb_id}: shows={shows}, clicks={clicks}, "
                            f"orders={orders}, CPO={cpo:.2f}, DRR={drr:.2f}%"
                        )

                    except Exception as e:
                        logger.error(f"Error saving stats for campaign {wb_id}: {e}")

        logger.info("✅ Daily stats collection done")

    except Exception as e:
        logger.error(f"Daily stats collection failed: {e}", exc_info=True)
