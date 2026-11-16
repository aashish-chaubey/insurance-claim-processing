from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["openai", "azure_openai"] = "openai"
    openai_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"
    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment: str | None = None
    database_url: str = "postgresql+psycopg://claims_app:claims_app_pw@localhost:5434/insurance_claims"
    env: str = "local"

    # Guardrails
    fraud_score_requires_investigation: float = 0.6  # >= this always routes to human fraud review
    settlement_auto_approve_max: float = 75000.0  # settlements above this always require approval
    low_confidence_threshold: float = 0.75

    @model_validator(mode="after")
    def validate_llm_configuration(self) -> "Settings":
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if self.llm_provider == "azure_openai":
            missing = [
                name
                for name, value in (
                    ("AZURE_OPENAI_API_KEY", self.azure_openai_api_key),
                    ("AZURE_OPENAI_ENDPOINT", self.azure_openai_endpoint),
                    ("AZURE_OPENAI_DEPLOYMENT", self.azure_openai_deployment),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "Azure OpenAI requires the following settings: " + ", ".join(missing)
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
