import asyncpg
import logging

logger = logging.getLogger(__name__)

pool: asyncpg.Pool | None = None


async def init_db(database_url: str):
    global pool
    pool = await asyncpg.create_pool(
        database_url,
        min_size=2,
        max_size=10,
        command_timeout=60,
    )
    logger.info("✅ Database pool created")


async def close_db():
    global pool
    if pool:
        await pool.close()


async def execute(query: str, *args):
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)


async def fetch(query: str, *args):
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args):
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetchval(query: str, *args):
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)
