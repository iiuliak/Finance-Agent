import os
from datetime import date


class Settings:
    def __init__(self) -> None:
        self.database_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://vat:vat@localhost:5433/vat",
        )
        # Unset means today, so a fresh demo opens on the day it is seeded.
        raw_as_of = os.environ.get("AS_OF_DATE", "").strip()
        self.as_of_date = date.fromisoformat(raw_as_of) if raw_as_of else date.today()
        self.llm_mode = os.environ.get("LLM_MODE", "template")
        self.openai_base_url = os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
        self.openai_model = os.environ.get("OPENAI_MODEL", "")


def get_settings() -> Settings:
    return Settings()
