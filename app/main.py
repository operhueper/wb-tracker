import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

from app import database as db
from app.config import settings
from app.wb_api.client import WBClient
from app.collectors import campaigns as camp_collector
from app.collectors import daily_stats as stats_collector
from app.collectors import prices as price_collector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
wb_client: WBClient | None = None


async def _run_campaigns():
    await camp_collector.collect_campaign_snapshots(wb_client)


async def _run_prices():
    await price_collector.collect_prices(settings.articles_list)


async def _run_daily_stats():
    await stats_collector.collect_daily_stats(wb_client)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global wb_client

    logger.info("🚀 WB Tracker starting up...")
    await db.init_db(settings.database_url)

    wb_client = WBClient(settings.wb_api_token)

    # Ensure product articles exist in DB
    for article in settings.articles_list:
        await db.execute(
            "INSERT INTO products (wb_article) VALUES ($1) ON CONFLICT (wb_article) DO NOTHING",
            article,
        )
    logger.info(f"📦 Tracking articles: {settings.articles_list}")

    # ── Schedule tasks ──────────────────────────────────────────
    # Campaigns: every 15 minutes
    scheduler.add_job(_run_campaigns, IntervalTrigger(minutes=15), id="campaigns", max_instances=1)
    # Prices:    every hour
    scheduler.add_job(_run_prices, IntervalTrigger(hours=1), id="prices", max_instances=1)
    # Daily stats: 06:00 Moscow time
    scheduler.add_job(_run_daily_stats, CronTrigger(hour=6, minute=0), id="daily_stats", max_instances=1)

    scheduler.start()
    logger.info("⏰ Scheduler started")

    # Run immediately on launch (don't block startup)
    asyncio.create_task(_run_campaigns())
    asyncio.create_task(_run_prices())

    yield

    scheduler.shutdown(wait=False)
    await db.close_db()
    logger.info("👋 WB Tracker stopped")


app = FastAPI(
    title="WB Tracker",
    description="Tracks Wildberries ad campaign changes and prices",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/", tags=["health"])
async def root():
    return {"status": "ok", "service": "WB Tracker", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/health", tags=["health"])
async def health():
    """Health check — also keeps Render from sleeping."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "articles": settings.articles_list,
        "next_jobs": {
            job.id: job.next_run_time.isoformat() if job.next_run_time else None
            for job in scheduler.get_jobs()
        },
    }


@app.get("/stats", tags=["data"])
async def get_stats():
    """Summary stats from the database."""
    snapshots = await db.fetchval("SELECT COUNT(*) FROM campaign_snapshots") or 0
    changes = await db.fetchval("SELECT COUNT(*) FROM campaign_snapshots WHERE is_changed = true") or 0
    prices = await db.fetchval("SELECT COUNT(*) FROM price_history") or 0
    campaigns = await db.fetchval("SELECT COUNT(*) FROM campaigns") or 0
    return {
        "campaigns_tracked": campaigns,
        "total_snapshots": snapshots,
        "changes_detected": changes,
        "price_snapshots": prices,
    }


@app.get("/campaigns", tags=["data"])
async def get_campaigns():
    """List all tracked campaigns with latest snapshot."""
    rows = await db.fetch(
        """
        SELECT c.wb_campaign_id, c.name, c.status,
               s.bid, s.budget_daily, s.snapshot_at
        FROM campaigns c
        LEFT JOIN LATERAL (
            SELECT bid, budget_daily, snapshot_at
            FROM campaign_snapshots
            WHERE campaign_id = c.id
            ORDER BY snapshot_at DESC LIMIT 1
        ) s ON true
        ORDER BY c.name
        """
    )
    return [dict(r) for r in rows]


@app.get("/prices", tags=["data"])
async def get_prices(article: int | None = None):
    """Latest price snapshot per article (or filtered by article)."""
    if article:
        rows = await db.fetch(
            """
            SELECT wb_article, price_base, price_sale, price_spp,
                   spp_percent, discount_percent, snapshot_at
            FROM price_history
            WHERE wb_article = $1
            ORDER BY snapshot_at DESC LIMIT 24
            """,
            article,
        )
    else:
        rows = await db.fetch(
            """
            SELECT DISTINCT ON (wb_article)
                   wb_article, price_base, price_sale, price_spp,
                   spp_percent, discount_percent, snapshot_at
            FROM price_history
            ORDER BY wb_article, snapshot_at DESC
            """
        )
    return [dict(r) for r in rows]


@app.get("/changes", tags=["data"])
async def get_changes(limit: int = 50):
    """Recent campaign changes detected by the tracker."""
    rows = await db.fetch(
        """
        SELECT s.wb_campaign_id, c.name, s.bid, s.status,
               s.budget_daily, s.change_details, s.snapshot_at
        FROM campaign_snapshots s
        JOIN campaigns c ON c.id = s.campaign_id
        WHERE s.is_changed = true
          AND s.change_details::text != '{"event": "first_snapshot"}'
        ORDER BY s.snapshot_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


# ── Manual triggers ──────────────────────────────────────────────
@app.post("/collect/campaigns", tags=["trigger"])
async def trigger_campaigns():
    asyncio.create_task(_run_campaigns())
    return {"status": "triggered", "job": "campaigns"}


@app.post("/collect/prices", tags=["trigger"])
async def trigger_prices():
    asyncio.create_task(_run_prices())
    return {"status": "triggered", "job": "prices"}


@app.post("/collect/stats", tags=["trigger"])
async def trigger_stats(days_back: int = 30):
    """Trigger collection of historical campaign stats (clicks, spend, orders)."""
    asyncio.create_task(stats_collector.collect_daily_stats(wb_client, days_back))
    return {"status": "triggered", "job": "daily_stats", "days_back": days_back}

from pydantic import BaseModel

class ProductUpdate(BaseModel):
    cost_price: float
    wb_commission: float
    logistics_cost: float

@app.put("/products/{wb_article}", tags=["products"])
async def update_product_economics(wb_article: int, econ: ProductUpdate):
    """Update unit economics for margin calculation."""
    await db.execute(
        """
        UPDATE products
        SET cost_price = $1, wb_commission = $2, logistics_cost = $3, updated_at = now()
        WHERE wb_article = $4
        """,
        econ.cost_price, econ.wb_commission, econ.logistics_cost, wb_article
    )
    return {"status": "success", "article": wb_article}

@app.get("/products", tags=["products"])
async def get_products():
    rows = await db.fetch("SELECT wb_article, cost_price, wb_commission, logistics_cost FROM products ORDER BY wb_article")
    return [dict(r) for r in rows]
