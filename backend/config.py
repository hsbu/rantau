"""Server configuration; secret values never participate in public models."""

import re
from urllib.parse import urlsplit

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    app_env: str = "development"
    database_url: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = ""
    auth_enabled: bool = False
    auth_tenant_id: str = ""
    auth_trusted_origin: str = ""
    auth_demo_student_password: SecretStr | None = None
    auth_demo_sponsor_password: SecretStr | None = None

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
