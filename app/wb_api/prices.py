import httpx
import logging
from typing import List

logger = logging.getLogger(__name__)

CARD_URL = "https://card.wb.ru/cards/v2/detail"


async def get_product_prices(article_ids: List[int]) -> List[dict]:
    """
    Fetch product prices from public WB API (no token needed).
    Returns price_base, price_sale, SPP info for each article.
    dest=-1257786 = Moscow (largest buyer base, most representative SPP).
    """
    params = {
        "appType": "1",
        "curr": "rub",
        "dest": "-1257786",
        "nm": ";".join(str(x) for x in article_ids),
    }
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(CARD_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            products = data.get("data", {}).get("products", [])
            logger.info(f"Fetched prices for {len(products)} products")
            return products
    except Exception as e:
        logger.error(f"Failed to fetch prices: {e}")
        return []


def parse_price(product: dict) -> dict:
    """
    Extract pricing data from a product object.
    All WB prices are stored in kopecks (1 rub = 100 kopecks).
    """
    price_base = product.get("priceU", 0) / 100
    price_sale = product.get("salePriceU", 0) / 100
    discount_pct = product.get("sale", 0)        # продавческая скидка %
    spp_pct = product.get("spp", 0)              # скидка WB (СПП) %

    # Real buyer price = sale price minus SPP
    price_spp = round(price_sale * (1 - spp_pct / 100), 2) if spp_pct else price_sale

    # Also check clientPriceU which WB sometimes returns directly
    client_price_u = product.get("clientPriceU")
    if client_price_u:
        price_spp = client_price_u / 100

    return {
        "wb_article": product.get("id"),
        "price_base": price_base,
        "price_sale": price_sale,
        "price_spp": price_spp,
        "discount_percent": discount_pct,
        "spp_percent": spp_pct,
    }
