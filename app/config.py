from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    wb_api_token: str
    database_url: str
    product_articles: str = "437295425,398522523,478224791"

    @property
    def articles_list(self) -> List[int]:
        return [int(x.strip()) for x in self.product_articles.split(",")]

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
