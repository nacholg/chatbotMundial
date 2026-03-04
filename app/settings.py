from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    WHATSAPP_PHONE_NUMBER_ID: str
    WHATSAPP_ACCESS_TOKEN: str
    WHATSAPP_VERIFY_TOKEN: str
    WHATSAPP_API_VERSION: str = "v19.0"

    INTERNAL_SALES_WA_TO: str | None = None

    # Microsoft Graph / SharePoint Excel
    MS_TENANT_ID: str | None = None
    MS_CLIENT_ID: str | None = None
    MS_CLIENT_SECRET: str | None = None

    SP_HOSTNAME: str | None = None
    SP_SITE_PATH: str | None = None
    SP_EXCEL_FILE_PATH: str | None = None
    SP_EXCEL_TABLE_NAME: str = "Leads"

    MS_EXCEL_ENABLED: int = 0

settings = Settings()