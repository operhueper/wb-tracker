import logging
from datetime import date, timedelta
from .client import WBClient

logger = logging.getLogger(__name__)

# New API base (2026-03-05+)
ADV_V2_BASE = "https://advert-api.wildberries.ru"

# Status codes meaning
STATUS_MAP = {
    -1: "deleted",
    4: "ready_to_start",
    7: "ended",
    8: "refused",
    9: "active",
    11: "paused",
}

# We only care about active + paused campaigns
TRACKED_STATUSES = {9, 11, 4}


async def get_all_campaigns(client: WBClient) -> list:
    """
    Fetch all campaigns using the new WB API (2026-03-05+).
    GET /api/advert/v2/adverts  → returns all campaigns with full details.
    
    Each campaign has:
      - id: advertId
      - status: 9=active, 11=paused, 7=ended, etc.
      - settings.name: campaign name
      - nm_settings[].bids_kopecks.search: current CPM bid in kopecks
      - bid_type: 'manual' / 'auto'
    """
    data = await client.get(f"{ADV_V2_BASE}/api/advert/v2/adverts")
    if not data or not isinstance(data, dict):
        logger.warning("get_all_campaigns: empty or bad response")
        return []

    adverts = data.get("adverts", [])
    logger.info(f"get_all_campaigns: retrieved {len(adverts)} campaigns from API")
    return adverts


def extract_bid_from_v2(campaign: dict) -> float | None:
    """
    Extract CPM bid (in rubles) from the new /api/advert/v2/adverts response.
    Bid is stored in kopecks in nm_settings[].bids_kopecks.search
    """
    nm_settings = campaign.get("nm_settings", [])
    if nm_settings:
        # Use the highest bid among all nmIds in the campaign
        bids = []
        for nm in nm_settings:
            bids_kopecks = nm.get("bids_kopecks", {})
            search_bid = bids_kopecks.get("search", 0)
            if search_bid:
                bids.append(search_bid)
        if bids:
            return max(bids) / 100  # convert kopecks to rubles

    # Fallback for auto campaigns
    return None


def get_campaign_name(campaign: dict) -> str:
    """Extract campaign name from settings."""
    return campaign.get("settings", {}).get("name", "")


def get_yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


async def get_fullstats(client: WBClient, campaign_ids: list[int], begin_date: str, end_date: str) -> list:
    """
    Get full statistics for a list of campaigns on specified dates.
    New endpoint: POST /adv/v2/fullstats
    Accepts intervals.
    """
    if not campaign_ids:
        return []
    
    payload = [
        {"id": cid, "interval": {"begin": begin_date, "end": end_date}}
        for cid in campaign_ids
    ]
    
    # Send in chunks of 50 inside the function or assume caller chunks
    data = await client.post(
        f"{ADV_V2_BASE}/adv/v2/fullstats",
        data=payload
    )
    if isinstance(data, list):
        return data
    elif isinstance(data, dict) and "data" in data:
        return data["data"]
    return []
