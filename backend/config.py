"""Server configuration; secret values never participate in public models."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    app_env: str = "development"
    database_url: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_model: str = ""

    @property
    def classifier_configured(self) -> bool:
        return bool(self.openai_api_key and self.openai_model.strip())
