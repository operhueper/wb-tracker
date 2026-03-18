import asyncio
import logging
from datetime import date, timedelta
from .client import WBClient, ADV_BASE

logger = logging.getLogger(__name__)

# All meaningful campaign statuses
CAMPAIGN_STATUSES = [-1, 4, 7, 8, 9, 11]


async def get_all_campaigns(client: WBClient) -> list:
    """
    Fetch all campaigns across all statuses.
    WB API 2025: this endpoint requires POST method.
    """
    result = []
    for status in CAMPAIGN_STATUSES:
        # WB changed /adv/v1/promotion/adverts to POST in 2025
        data = await client.post(
            f"{ADV_BASE}/adv/v1/promotion/adverts",
            data=None,   # empty body — params go in URL
            params={"status": status, "limit": 100, "offset": 0},
        )
        if isinstance(data, list):
            result.extend(data)
        await asyncio.sleep(0.3)  # rate limit safety
    return result


async def get_campaign_detail(client: WBClient, campaign_id: int) -> dict | None:
    """Get detailed campaign info including CPM bid."""
    return await client.get(
        f"{ADV_BASE}/adv/v0/advert",
        params={"id": campaign_id},
    )


async def get_campaign_words(client: WBClient, campaign_id: int) -> dict | None:
    """Get keyword statistics for a campaign."""
    return await client.get(
        f"{ADV_BASE}/adv/v1/stat/words",
        params={"id": campaign_id},
    )


async def get_fullstats(client: WBClient, campaign_ids: list[int], dates: list[str]) -> list:
    """Get full statistics for a list of campaigns on specified dates."""
    if not campaign_ids:
        return []
    body = [{"id": cid, "dates": dates} for cid in campaign_ids]
    result = await client.post(f"{ADV_BASE}/adv/v3/fullstats", data=body)
    if isinstance(result, list):
        return result
    return []


def extract_bid_from_detail(detail: dict) -> float | None:
    """Extract CPM bid from campaign detail response."""
    if not detail:
        return None
    params = detail.get("params", [])
    if params and isinstance(params, list):
        price = params[0].get("price")
        if price is not None:
            return float(price)
    return detail.get("bet") or detail.get("cpm")


def get_yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()



async def get_campaign_detail(client: WBClient, campaign_id: int) -> dict | None:
    """Get detailed campaign info including CPM bid."""
    return await client.get(
        f"{ADV_BASE}/adv/v0/advert",
        params={"id": campaign_id},
    )


async def get_campaign_words(client: WBClient, campaign_id: int) -> dict | None:
    """Get keyword statistics for a campaign."""
    return await client.get(
        f"{ADV_BASE}/adv/v1/stat/words",
        params={"id": campaign_id},
    )


async def get_fullstats(client: WBClient, campaign_ids: list[int], dates: list[str]) -> list:
    """Get full statistics for a list of campaigns on specified dates."""
    if not campaign_ids:
        return []
    body = [{"id": cid, "dates": dates} for cid in campaign_ids]
    result = await client.post(f"{ADV_BASE}/adv/v3/fullstats", data=body)
    if isinstance(result, list):
        return result
    return []


def extract_bid_from_detail(detail: dict) -> float | None:
    """Extract CPM bid from campaign detail response."""
    if not detail:
        return None
    # Type 9 (unified/manual): bid in params[0].price
    params = detail.get("params", [])
    if params and isinstance(params, list):
        price = params[0].get("price")
        if price is not None:
            return float(price)
    # Fallback: bet field
    return detail.get("bet") or detail.get("cpm")


def get_yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()
