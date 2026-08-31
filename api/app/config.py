import os


class Settings:
    """Runtime configuration, sourced from environment variables (see docker-compose.yml)."""

    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434/v1")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2")

    smtp_host: str = os.getenv("SMTP_HOST", "mailhog")
    smtp_port: int = int(os.getenv("SMTP_PORT", "1025"))
    smtp_from: str = os.getenv("SMTP_FROM", "ai-router@example.com")


settings = Settings()
