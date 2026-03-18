import asyncio
import json
import logging

from app import database as db
from app.wb_api.client import WBClient
from app.wb_api import advert as adv

logger = logging.getLogger(__name__)


async def collect_campaign_snapshots(client: WBClient):
    """
    Every 15 minutes:
    - Fetch all campaigns from WB ADV API
    - For each: get current bid, status, budget
    - Compare with last snapshot → detect changes
    - Save snapshot to DB
    """
    logger.info("📸 Campaign snapshot collection started")
    try:
        campaigns = await adv.get_all_campaigns(client)
        if not campaigns:
            logger.warning("No campaigns returned from API")
            return

        logger.info(f"Processing {len(campaigns)} campaigns")

        for camp in campaigns:
            try:
                wb_id = camp.get("advertId")
                if not wb_id:
                    continue

                # Upsert campaign record
                camp_uuid = await db.fetchval(
                    """
                    INSERT INTO campaigns (wb_campaign_id, name, campaign_type, status)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (wb_campaign_id) DO UPDATE
                      SET name = EXCLUDED.name,
                          status = EXCLUDED.status,
                          updated_at = now()
                    RETURNING id
                    """,
                    wb_id,
                    camp.get("name", ""),
                    camp.get("type"),
                    camp.get("status"),
                )

                # Get current bid from campaign detail
                detail = await adv.get_campaign_detail(client, wb_id)
                await asyncio.sleep(0.2)

                current_bid = adv.extract_bid_from_detail(detail) if detail else None
                current_status = camp.get("status")
                current_daily_budget = camp.get("dailyBudget")

                # Compare with last snapshot
                last = await db.fetchrow(
                    """
                    SELECT bid, status, budget_daily
                    FROM campaign_snapshots
                    WHERE wb_campaign_id = $1
                    ORDER BY snapshot_at DESC
                    LIMIT 1
                    """,
                    wb_id,
                )

                is_changed = False
                change_details = {}

                if last:
                    prev_bid = float(last["bid"]) if last["bid"] is not None else None
                    if prev_bid != current_bid:
                        is_changed = True
                        change_details["bid"] = {"from": prev_bid, "to": current_bid}
                    if last["status"] != current_status:
                        is_changed = True
                        change_details["status"] = {"from": last["status"], "to": current_status}
                    prev_budget = float(last["budget_daily"]) if last["budget_daily"] is not None else None
                    if prev_budget != current_daily_budget:
                        is_changed = True
                        change_details["budget_daily"] = {"from": prev_budget, "to": current_daily_budget}
                else:
                    # First snapshot — mark as new
                    is_changed = True
                    change_details["event"] = "first_snapshot"

                await db.execute(
                    """
                    INSERT INTO campaign_snapshots
                      (campaign_id, wb_campaign_id, bid, status, budget_daily,
                       is_changed, change_details, raw_data)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    camp_uuid,
                    wb_id,
                    current_bid,
                    current_status,
                    current_daily_budget,
                    is_changed,
                    json.dumps(change_details),
                    json.dumps(camp),
                )

                if is_changed and change_details.get("event") != "first_snapshot":
                    logger.info(f"🔔 Campaign {wb_id} CHANGED: {change_details}")

            except Exception as e:
                logger.error(f"Error processing campaign {camp.get('advertId')}: {e}")
                continue

        logger.info("✅ Campaign snapshot collection done")

    except Exception as e:
        logger.error(f"Campaign collection failed: {e}", exc_info=True)
