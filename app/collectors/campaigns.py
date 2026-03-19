import json
import logging

from app import database as db
from app.wb_api.client import WBClient
from app.wb_api import advert as adv

logger = logging.getLogger(__name__)

# Only track active/paused/ready statuses — skip old archived/deleted
TRACKED_STATUSES = {9, 11, 4}


async def collect_campaign_snapshots(client: WBClient):
    """
    Every 15 minutes:
    - Fetch all campaigns via new GET /api/advert/v2/adverts
    - Filter to active/paused only
    - Extract bid (in rubles), status, name
    - Compare with last snapshot → detect changes
    - Save snapshot to DB
    """
    logger.info("📸 Campaign snapshot collection started")
    try:
        all_campaigns = await adv.get_all_campaigns(client)
        if not all_campaigns:
            logger.warning("No campaigns returned from API")
            return

        # Filter to statuses we care about
        campaigns = [c for c in all_campaigns if c.get("status") in TRACKED_STATUSES]
        logger.info(f"Processing {len(campaigns)} active/paused campaigns (out of {len(all_campaigns)} total)")

        for camp in campaigns:
            try:
                wb_id = camp.get("id")
                if not wb_id:
                    continue

                camp_name = adv.get_campaign_name(camp)
                current_bid = adv.extract_bid_from_v2(camp)
                current_status = camp.get("status")
                # Budget not directly available in v2 — store as None for now
                current_daily_budget = None

                # Upsert campaign record
                # Note: campaign_type in DB is INT, but new API returns strings ('manual','unified')
                # We store the bid_type string in the name for reference, and NULL for campaign_type int
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
                    camp_name,
                    None,  # campaign_type is INT in DB; new API returns strings — store NULL
                    current_status,
                )

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
                    logger.info(f"🔔 Campaign {wb_id} '{camp_name}' CHANGED: {change_details}")

            except Exception as e:
                logger.error(f"Error processing campaign {camp.get('id')}: {e}", exc_info=True)
                continue

        logger.info("✅ Campaign snapshot collection done")

    except Exception as e:
        logger.error(f"Campaign collection failed: {e}", exc_info=True)
