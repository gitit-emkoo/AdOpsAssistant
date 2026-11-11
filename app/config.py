from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AdOps Assistant"
    app_base_url: str = "http://localhost:8000"
    demo_mode: bool = True
    timezone: str = "Asia/Seoul"
    database_path: Path = DATA_DIR / "assistant.db"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""

    google_ads_developer_token: str = ""
    google_ads_client_id: str = ""
    google_ads_client_secret: str = ""
    google_ads_refresh_token: str = ""
    google_ads_customer_id: str = ""
    google_ads_login_customer_id: str = ""

    meta_access_token: str = ""
    meta_ad_account_id: str = ""
    meta_api_version: str = "v21.0"
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_token_expires_at: str = ""

    @property
    def email_recipients(self) -> list[str]:
        return [e.strip() for e in self.email_to.split(",") if e.strip()]

    @property
    def google_ads_configured(self) -> bool:
        # 2026-09 이후 developer token은 선택 사항(헤더에 있어도 무시될 수 있음).
        # OAuth + Customer ID 만 있으면 실연동 시도합니다.
        return bool(
            self.google_ads_client_id
            and self.google_ads_client_secret
            and self.google_ads_refresh_token
            and self.google_ads_customer_id
        )

    @property
    def meta_configured(self) -> bool:
        return bool(self.meta_access_token and self.meta_ad_account_id)

    @property
    def meta_app_credentials_ready(self) -> bool:
        return bool(self.meta_app_id and self.meta_app_secret)

    @property
    def email_configured(self) -> bool:
        return bool(
            self.smtp_user
            and self.smtp_password
            and (self.email_from or self.smtp_user)
            and self.email_recipients
        )

    @property
    def llm_configured(self) -> bool:
        return bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()
