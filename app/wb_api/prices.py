import httpx
import asyncio
import logging
from typing import List

logger = logging.getLogger(__name__)

# Official Seller API for prices (works on Russian servers like Render Frankfurt)
PRICES_URL = "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"
# Fallback: old seller API
PRICES_URL_V1 = "https://seller-api.wildberries.ru/public/api/v1/info"


async def get_product_prices(article_ids: List[int], token: str) -> List[dict]:
    """
    Fetch product prices from the official WB Seller Prices API.
    Requires seller token. Returns list of product price objects.
    """
    headers = {"Authorization": token}
    results = []

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for nm_id in article_ids:
                try:
                    resp = await client.get(
                        PRICES_URL,
                        headers=headers,
                        params={"limit": 1, "offset": 0, "filterNmID": nm_id},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        goods = data.get("data", {}).get("listGoods", [])
                        if goods:
                            results.append({"nmId": nm_id, "goods": goods[0]})
                    elif resp.status_code == 404:
                        logger.warning(f"Article {nm_id} not found in prices API")
                    else:
                        logger.warning(f"Price API returned {resp.status_code} for {nm_id}: {resp.text[:200]}")
                    await asyncio.sleep(0.3)
                except Exception as e:
                    logger.error(f"Failed to fetch price for {nm_id}: {e}")

        logger.info(f"Fetched prices for {len(results)} / {len(article_ids)} products")
        return results

    except Exception as e:
        logger.error(f"Failed to fetch prices: {e}")
        return []


def parse_price(raw: dict) -> dict:
    """
    Extract pricing data from v2 listGoods response.
    
    Structure: raw = {nmId: int, goods: {...}}
    goods contains: price, discount, spp, priceWithDiscount, promoCode, etc.
    """
    nm_id = raw.get("nmId")
    goods = raw.get("goods", {})

    # Seller price (before discounts)
    price_base = goods.get("price", 0)

    # Seller discount %
    discount_pct = goods.get("discount", 0)

    # Price after seller discount
    price_sale = round(price_base * (1 - discount_pct / 100), 2)

    # SPP = WB discount for loyal customers (%)
    spp_pct = goods.get("spp", 0)

    # Final buyer price (after both seller discount + SPP)
    # WB sometimes returns this directly
    client_price = goods.get("priceWithDiscount")
    if client_price:
        price_spp = client_price
    else:
        price_spp = round(price_sale * (1 - spp_pct / 100), 2) if spp_pct else price_sale

    return {
        "wb_article": nm_id,
        "price_base": price_base,
        "price_sale": price_sale,
        "price_spp": price_spp,
        "discount_percent": discount_pct,
        "spp_percent": spp_pct,
    }
