import os
from datetime import date


class Settings:
    def __init__(self) -> None:
        self.database_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://vat:vat@localhost:5433/vat",
        )
        self.as_of_date = date.fromisoformat(os.environ.get("AS_OF_DATE", "2026-11-15"))
        self.llm_mode = os.environ.get("LLM_MODE", "template")
        self.openai_base_url = os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
        self.openai_model = os.environ.get("OPENAI_MODEL", "")


def get_settings() -> Settings:
    return Settings()
