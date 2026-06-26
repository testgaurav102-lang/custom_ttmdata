"""
Centralised application configuration.

All environment variables are declared here via Pydantic-Settings so that:
- Every setting has a clear name, type, and default value.
- Secrets never appear as hardcoded strings in application code.
- Configuration can be validated at startup rather than at runtime.

Usage::

    from app.config import settings

    settings.aws_bucket   # "my-bucket"
    settings.llm_model    # "datarobot-deployed-llm"
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_name: str = "Sales Intel Agent"
    debug: bool = False

    # ------------------------------------------------------------------
    # File storage
    # ------------------------------------------------------------------
    base_url: str = ""
    upload_dir: str = "uploads"
    max_file_size_mb: int = 5
    max_file_upload_count: int = 1
    file_url_expiry_seconds: int = 3600

    # ------------------------------------------------------------------
    # API metadata
    # ------------------------------------------------------------------
    default_model: str = "gpt-5 mini"
    supported_models: list[dict] = [
        {
            "modelName": "gpt-5 mini",
            "modes": ["quick_search"],
            "defaultMode": "quick_search",
        }
    ]

    # ------------------------------------------------------------------
    # LLM (DataRobot / OpenAI-compatible endpoint)
    # ------------------------------------------------------------------
    datarobot_api_token: str = ""
    chat_api_url: str = ""

    # Internal model identifier sent to the LLM API.  Override via
    # LLM_MODEL env var to switch deployments without code changes.
    llm_model: str = "datarobot-deployed-llm"

    # ------------------------------------------------------------------
    # AWS / S3
    # ------------------------------------------------------------------
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    region_name: str = ""
    aws_bucket: str = "s3-ai-demo-bucket"

    # ------------------------------------------------------------------
    # Mermaid / PDF rendering
    # ------------------------------------------------------------------
    # Path to the Puppeteer config JSON used by the Mermaid CLI.
    # Leave empty to use the bundled default at app/services/puppeteer-config.json.
    puppeteer_config_path: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
