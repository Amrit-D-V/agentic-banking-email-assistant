from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "HDFC-Intelligent-Email-Agent"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    LOGS_DIR: Path = BASE_DIR / "logs"
    APP_LOG_FILE: Path = LOGS_DIR / "app.log"
    DATABASE_URL: str = f"sqlite:///{LOGS_DIR / 'email_automation.db'}"

    LLM_PROVIDER: Literal["ollama", "mock", "openai"] = "ollama"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2:3b"
    LLM_PERSONALISED_OPENING: bool = False
    TRANSLATE_NON_ENGLISH: bool = True
    NLU_SINGLE_CALL: bool = False
    LLM_TEMPERATURE: float = 0.1
    LLM_REQUEST_TIMEOUT_SECONDS: float = 30.0

    BANKING_API_HOST: str = "127.0.0.1"
    BANKING_API_PORT: int = 8000
    BANKING_API_TRANSPORT: Literal["inprocess", "http", "mcp"] = "inprocess"
    API_TIMEOUT_SECONDS: float = 2.0
    API_MAX_RETRIES: int = 2
    API_RETRY_BACKOFF_SECONDS: float = 0.2
    API_CACHE_SECONDS: float = 60.0
    CIRCUIT_FAILURE_THRESHOLD: int = 5
    CIRCUIT_RESET_SECONDS: float = 30.0

    MOCK_FAILURE_RATE: float = 0.0
    MOCK_SLOW_RESPONSE_SECONDS: float = 5.0

    DEMO_CUSTOMER_EMAIL: str = "john.doe@example.com"

    MCP_SERVER_NAME: str = "hdfc-core-banking-mcp"
    MCP_SERVER_VERSION: str = "1.0.0"

    MASK_PII_IN_LOGS: bool = True
    MASK_PII_IN_RESPONSES: bool = True
    ENFORCE_SENDER_OWNERSHIP: bool = True
    REQUIRE_REGISTERED_SENDER: bool = True
    MAX_ENTITIES_PER_EMAIL: int = 5

    ADMIN_USER: str = "admin"
    ADMIN_PASSWORD: str = ""

    HITL_ENABLED: bool = False
    HITL_CONFIDENCE_THRESHOLD: float = 0.8

    ATTACHMENTS_DIR: Path = BASE_DIR / "downloads"
    OCR_LANGUAGES: str = "eng"

    MAX_PROCESSING_TIMEOUT_SECONDS: float = 15.0
    RESPONSE_SLA_MS: float = 10000.0

    EMAIL_USER: str = ""
    EMAIL_PASS: str = ""
    IMAP_HOST: str = "imap.gmail.com"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    WORKER_CONCURRENCY: int = 4
    WORKER_BATCH_SIZE: int = 20

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
