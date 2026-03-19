import json
import logging
from typing import List

from app import database as db
from app.wb_api.prices import get_product_prices, parse_price
from app.config import settings

logger = logging.getLogger(__name__)


async def collect_prices(article_ids: List[int]):
    """
    Every hour:
    - Fetch public prices for all articles (no token needed)
    - Extract price_base, price_sale, SPP %, price_with_SPP
    - Save snapshot to price_history
    - Recalculate margin if cost_price is set in products table
    """
    logger.info(f"💰 Price collection for articles: {article_ids}")

    try:
        raw_products = await get_product_prices(article_ids, settings.wb_api_token)
        if not raw_products:
            logger.warning("No product data returned from WB card API")
            return

        for raw in raw_products:
            try:
                parsed = parse_price(raw)
                wb_article = parsed["wb_article"]

                # Get product record if exists
                prod = await db.fetchrow(
                    "SELECT id, cost_price, wb_commission, logistics_cost FROM products WHERE wb_article = $1",
                    wb_article,
                )
                prod_uuid = prod["id"] if prod else None

                # Insert price snapshot
                snap_id = await db.fetchval(
                    """
                    INSERT INTO price_history
                      (wb_article, product_id, price_base, price_sale, price_spp,
                       spp_percent, discount_percent, raw_data)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING id
                    """,
                    wb_article,
                    prod_uuid,
                    parsed["price_base"],
                    parsed["price_sale"],
                    parsed["price_spp"],
                    parsed["spp_percent"],
                    parsed["discount_percent"],
                    json.dumps(raw),
                )

                logger.info(
                    f"  Article {wb_article}: base={parsed['price_base']:.2f} → "
                    f"sale={parsed['price_sale']:.2f} → "
                    f"SPP {parsed['spp_percent']}% → final={parsed['price_spp']:.2f}"
                )

                # Calculate margin if cost price is set
                if prod and prod["cost_price"] and prod["cost_price"] > 0:
                    revenue = parsed["price_spp"]
                    cost = float(prod["cost_price"])
                    commission_pct = float(prod["wb_commission"] or 0)
                    logistics = float(prod["logistics_cost"] or 0)

                    commission_amt = revenue * commission_pct / 100
                    gross_profit = revenue - cost - commission_amt - logistics
                    margin_pct = round(gross_profit / revenue * 100, 4) if revenue > 0 else 0

                    await db.execute(
                        """
                        INSERT INTO margin_calculations
                          (product_id, price_snapshot_id, revenue, cost_price,
                           wb_commission_amt, logistics_amt, gross_profit, margin_pct)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """,
                        prod_uuid, snap_id, revenue, cost,
                        commission_amt, logistics, gross_profit, margin_pct,
                    )
                    logger.info(
                        f"  Margin for {wb_article}: revenue={revenue:.2f}, "
                        f"profit={gross_profit:.2f}, margin={margin_pct:.1f}%"
                    )

            except Exception as e:
                logger.error(f"Error processing article {raw.get('id')}: {e}")
                continue

        logger.info("✅ Price collection done")

    except Exception as e:
        logger.error(f"Price collection failed: {e}", exc_info=True)
