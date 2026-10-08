from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    NAVI_DB_HOST: str
    NAVI_DB_PORT: int = 5432
    NAVI_DB_NAME: str = "navi"
    NAVI_DB_USER: str = "navi"
    NAVI_DB_PASSWORD: str
    NAVI_DB_SSLMODE: str = "require"
    NAVI_SECRET_KEY: str
    NAVI_ADMIN_EMAIL: str = "admin@example.com"
    NAVI_ADMIN_INITIAL_PASSWORD: str = ""
    NAVI_BASE_PATH: str = "/navi"
    NAVI_PUBLIC_URL: str = "https://sonar.orcati.com.br/navi/"
    NAVI_COOKIE_SECURE: bool = True
    NAVI_SESSION_HOURS: int = 12
    NAVI_TZ: str = "America/Sao_Paulo"
    NAVI_STORAGE: str = "/data/storage"

    # Integracoes (podem ser sobrescritas no painel -> tabela settings)
    ZABBIX_URL: str = "https://sonar.orcati.com.br/zabbix/api_jsonrpc.php"
    ZABBIX_API_TOKEN: str = ""
    EVOLUTION_API_URL: str = "https://orcafy.orcati.com.br/evolution"
    EVOLUTION_INSTANCE: str = ""
    EVOLUTION_API_KEY: str = ""
    ACRONIS_URL: str = ""
    ACRONIS_CLIENT_ID: str = ""
    ACRONIS_CLIENT_SECRET: str = ""
    EMS_HOST: str = ""
    EMS_PORT: int = 443
    EMS_API_KEY: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    NAVI_WEBHOOK_TOKEN: str = ""
    # IA (futuro)
    NAVI_LLM_PROVIDER: str = "none"
    NAVI_LLM_API_KEY: str = ""

    @property
    def db_url(self) -> str:
        return (
            f"postgresql+psycopg://{quote_plus(self.NAVI_DB_USER)}:{quote_plus(self.NAVI_DB_PASSWORD)}"
            f"@{self.NAVI_DB_HOST}:{self.NAVI_DB_PORT}/{self.NAVI_DB_NAME}?sslmode={self.NAVI_DB_SSLMODE}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
