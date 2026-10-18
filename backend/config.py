"""Server configuration; secret values never participate in public models."""

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    app_env: str = "development"
    database_url: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = ""
    agent_web_research_enabled: bool = False
    openrouter_research_model: str = ""
    openrouter_max_tokens: int = Field(default=2048, ge=512, le=8192)
    openrouter_reasoning_effort: (
        Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None
    ) = None
    auth_enabled: bool = False
    auth_tenant_id: str = ""
    auth_trusted_origin: str = ""
    auth_demo_student_password: SecretStr | None = None
    auth_demo_sponsor_password: SecretStr | None = None
    approval_ttl_seconds: int = Field(default=600, ge=1, le=3600)

    @field_validator("openrouter_reasoning_effort", mode="before")
    @classmethod
    def optional_reasoning_effort(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def auth_configured(self) -> bool:
        try:
            origin = urlsplit(self.auth_trusted_origin)
            # Validate the port too: urlsplit otherwise accepts a malformed authority.
            _ = origin.port
        except ValueError:
            return False
        return bool(
            self.auth_enabled
            and self.database_url
            and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", self.auth_tenant_id)
            and origin.hostname
            and not origin.username
            and not origin.password
            and not origin.path
            and not origin.query
            and not origin.fragment
            and origin.scheme
            in ({"http", "https"} if self.app_env in {"development", "test"} else {"https"})
            and (
                origin.scheme == "https"
                or origin.hostname in {"localhost", "127.0.0.1", "::1"}
                or (self.app_env == "test" and origin.hostname == "testserver")
            )
            and self.auth_trusted_origin == f"{origin.scheme}://{origin.netloc}"
        )

    @property
    def auth_cookie_secure(self) -> bool:
        return urlsplit(self.auth_trusted_origin).scheme == "https"

    @property
    def classifier_configured(self) -> bool:
        return bool(
            self.openrouter_api_key
            and self.openrouter_api_key.get_secret_value().strip()
            and self.openrouter_model.strip()
        )
