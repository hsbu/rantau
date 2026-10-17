"""Server configuration; secret values never participate in public models."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    app_env: str = "development"
    database_url: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = ""

    @property
    def classifier_configured(self) -> bool:
        return bool(
            self.openrouter_api_key
            and self.openrouter_api_key.get_secret_value().strip()
            and self.openrouter_model.strip()
        )
