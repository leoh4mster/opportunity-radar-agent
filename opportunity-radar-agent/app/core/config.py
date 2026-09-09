from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Opportunity Radar Agent"
    database_url: str = "sqlite:///./opportunity_radar.db"
    log_level: str = "INFO"
    log_format: str = "json"
    slow_request_ms: int = 1000

    # DeepSeek is optional. Core import and recommendation flows fall back to
    # deterministic local rules when no API key is configured.
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    weixin_search_mcp_config: str = ""
    weixin_search_mcp_server: str = "weixin_search_mcp"
    weixin_search_mcp_tool: str = ""
    weixin_search_mcp_transport: str = "http"
    weixin_search_mcp_url: str = ""
    weixin_search_max_results: int = 5

    web_search_provider: str = "bocha"
    bocha_api_key: str = ""
    bocha_base_url: str = "https://api.bochaai.com/v1/web-search"
    bocha_search_count: int = 5

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
