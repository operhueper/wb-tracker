import httpx
import asyncio
import logging

logger = logging.getLogger(__name__)

ADV_BASE = "https://advert-api.wildberries.ru"


class WBClient:
    def __init__(self, token: str):
        self.headers = {
            "Authorization": token,
            "Content-Type": "application/json",
        }

    async def get(self, url: str, params: dict = None, retries: int = 3) -> dict | list | None:
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(url, headers=self.headers, params=params)
                    if resp.status_code == 429:
                        wait = 2 ** attempt
                        logger.warning(f"Rate limited, waiting {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    if resp.status_code == 204:
                        return []
                    resp.raise_for_status()
                    return resp.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP {e.response.status_code} on GET {url}: {e.response.text[:200]}")
                if attempt == retries - 1:
                    return None
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"GET {url} attempt {attempt + 1} failed: {e}")
                if attempt == retries - 1:
                    return None
                await asyncio.sleep(1)
        return None

    async def post(self, url: str, data: dict | list | None, params: dict = None, retries: int = 3) -> dict | list | None:
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(url, headers=self.headers, json=data, params=params)
                    if resp.status_code == 429:
                        wait = 2 ** attempt
                        logger.warning(f"Rate limited, waiting {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    return resp.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP {e.response.status_code} on POST {url}: {e.response.text[:200]}")
                if attempt == retries - 1:
                    return None
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"POST {url} attempt {attempt + 1} failed: {e}")
                if attempt == retries - 1:
                    return None
                await asyncio.sleep(1)
        return None

